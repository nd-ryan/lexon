# Case Upload & Knowledge Graph Submission

This document describes the two methods for uploading cases to the Knowledge Graph (Neo4j).

## Overview

Lexon supports two workflows for getting case data into the Knowledge Graph:

| Method | Use Case | Access | Location |
|--------|----------|--------|----------|
| **Single Case Upload** | Create a case from a document, then review/edit/submit | **Admin** (upload) + **Editor** (edit/submit) | Upload + Case Editor |
| **Bulk Upload** | Processing multiple cases at once | **Admin** | `/admin/bulk-upload` |

Both methods ultimately use the same backend endpoint (`/api/kg/submit`) for the final KG submission.

---

## Single Case Upload (Case Editor)

### User Flow

1. **Upload Document (admin)**: Admin uploads a `.docx` or `.pdf` via the case upload page
2. **AI Extraction**: Backend extracts case data using CrewAI (`CaseExtractFlow`)
3. **Review & Edit (editor+)**: Editors review extracted data in the Case Editor and make corrections
4. **Save**: Changes are saved to Postgres (`extracted` column)
5. **Submit to KG (editor+)**: Editors click "Submit to KG" to publish to Neo4j

**Notes:**
- Users with role `user` can view cases and use chat, but cannot edit cases or submit to KG.
- Uploading new documents is intentionally restricted to admins to control ingestion.

### Technical Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Case Editor    │────▶│  POST /api/kg/   │────▶│   KGFlow        │
│  (Frontend)     │     │  submit          │     │   (Backend)     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                         │
                        ┌──────────────────┐             ▼
                        │  Neo4j Upload    │◀────────────┘
                        │  + Embeddings    │
                        └──────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │  Postgres Save   │
                        │  (kg_extracted)  │
                        └──────────────────┘
```

### Key Files

- **Frontend**: `src/app/cases/[id]/page.tsx` - Case Editor with Submit button
- **Hook**: `src/hooks/cases/useCaseSave.ts` - `submitToKg()` function
- **API Proxy**: `src/app/api/kg/submit/route.ts` - Next.js route
- **Backend**: `ai-backend/app/routes/kg.py` - `/submit` endpoint
- **KG Flow**: `ai-backend/app/flow_kg/flow_kg.py` - Transformation & embedding generation

### Embedding Validation

After successful upload, the backend validates that all required embeddings are present:

```json
{
  "success": true,
  "nodes": 14,
  "edges": 28,
  "embeddings_complete": true,
  "embeddings_summary": {
    "expected": 8,
    "present": 8,
    "missing": 0
  }
}
```

If embeddings are missing, a warning banner appears in the footer:

> ⚠️ KG uploaded with missing embeddings: 2 of 8 embeddings missing. Click "Submit to KG" again to retry embedding generation.

The user can retry by clicking "Submit to KG" again - the system will detect missing embeddings and regenerate them.

---

## Bulk Upload (Admin)

### User Flow

1. **Select Files**: Admin selects multiple `.docx` or `.pdf` files
2. **Start Processing**: Click "Start Bulk Processing"
3. **Sequential Processing**: Each case is processed one at a time:
   - File upload → AI extraction → KG submission
4. **Monitor Progress**: Status shown for each file (pending, extracting, uploading, completed/failed)
5. **Handle Warnings**: Cases with missing embeddings shown in amber, with Retry button

### Technical Flow

```
┌─────────────────┐     For each file:
│  Bulk Upload    │     ┌──────────────────────────────────────────┐
│  Page           │────▶│ 1. POST /api/cases/upload (start job)    │
└─────────────────┘     │ 2. SSE /api/cases/upload/progress/{job}  │
                        │ 3. POST /api/kg/submit (when extraction  │
                        │    completes)                             │
                        └──────────────────────────────────────────┘
```

### Key Files

- **Frontend**: `src/app/admin/bulk-upload/page.tsx` - Admin bulk upload page
- **Upload API**: `src/app/api/cases/upload/route.ts` - File upload handler
- **Progress SSE**: `src/app/api/cases/upload/progress/[jobId]/route.ts` - Extraction progress stream
- **KG Submit**: Same as single case (`/api/kg/submit`)

### Status Indicators

| Status | Color | Meaning |
|--------|-------|---------|
| ⏳ Waiting | Gray | Not yet started |
| 📄 Extracting | Blue | AI extraction in progress |
| 🔄 Uploading to KG | Blue | Submitting to Neo4j |
| ✅ Complete | Green | Successfully uploaded with all embeddings |
| ⚠️ Missing embeddings | Amber | Uploaded but some embeddings failed |
| ❌ Failed | Red | Error during processing |

### Retry Logic

For cases with missing embeddings (amber status):
1. Click the "Retry" button next to the case
2. System re-runs `/api/kg/submit` for that case
3. `KGFlow` detects missing embeddings and regenerates them
4. Status updates to green when complete

---

## Backend: KGFlow Processing

Both upload methods use the same `KGFlow` for transformation:

### Steps

1. **Schema Validation**: Validate node/edge structure against `schema_v3.json`
2. **ID Generation**: Generate UUIDs for nodes without `*_id` properties
3. **Check Existing Embeddings**: Query Neo4j to see which nodes need embeddings
4. **Compute Embeddings**: Generate vector embeddings for text fields
5. **Upload to Neo4j**: Write nodes and edges in a single transaction
6. **Post-Upload Validation**: Verify all embeddings are present

### Embedding Detection

The `check_existing_for_embeddings` step detects nodes needing embeddings when:

1. **Node is new**: Not yet in Neo4j
2. **Text changed**: Source text field has different content
3. **Embedding missing**: Text exists but embedding property is null/missing

```python
# Example: Node has disposition_text but no disposition_text_embedding
# → Flagged for embedding generation
```

---

## Data Storage

### Postgres Columns

| Column | Purpose |
|--------|---------|
| `extracted` | Current draft data (user-editable) |
| `kg_extracted` | Last published snapshot (mirrors Neo4j) |
| `kg_submitted_at` | Timestamp of last KG submission |
| `kg_submitted_by` | User who last submitted to KG |

### Neo4j Data

- Contains the authoritative Knowledge Graph
- Nodes have vector embedding properties (e.g., `summary_embedding`)
- Catalog nodes (Domain, Forum, etc.) are shared across cases

---

## Error Handling

### Upload Failures

If Neo4j upload fails:
- Postgres is **not** updated (transaction rolled back)
- User can retry without data loss

### Missing Embeddings

If embeddings fail to generate:
- Upload still succeeds (data is in Neo4j)
- Warning shown to user
- Retry regenerates missing embeddings
- Postgres `kg_extracted` is updated regardless

### Validation Errors

Before submission:
- Required field validation runs
- Cardinality constraints validated (see below)
- User sees error message if validation fails
- Submission blocked until errors fixed

### Cardinality Validation

The system validates relationship cardinality constraints defined in `schema_v3.json`:

| Cardinality | Source Limit | Target Limit | Example |
|-------------|--------------|--------------|---------|
| `one-to-one` | 1 edge max | 1 reference max | Ruling → SETS → Issue |
| `one-to-many` | unlimited | 1 reference max | Case → HAS_PROCEEDING → Proceeding |
| `many-to-one` | 1 edge max | unlimited | Forum → PART_OF → Jurisdiction |
| `many-to-many` | unlimited | unlimited | Issue → RELATES_TO_DOCTRINE → Doctrine |

**Example violation:**
```
Cardinality violation: Ruling-[SETS] is one-to-one, but source 'n1' has 3 edges
```

This prevents issues like a single Ruling being linked to multiple Issues, which would indicate extraction errors.

---

## API Reference

### POST /api/kg/submit

Submit case to Knowledge Graph.

**Request:**
```json
{
  "id": "case-uuid"
}
```

**Response:**
```json
{
  "success": true,
  "nodes": 14,
  "edges": 28,
  "embeddings_complete": true,
  "missing_embeddings": [],
  "embeddings_summary": {
    "expected": 8,
    "present": 8,
    "missing": 0
  }
}
```

**Response (with warnings):**
```json
{
  "success": true,
  "nodes": 14,
  "edges": 28,
  "embeddings_complete": false,
  "missing_embeddings": [
    "Argument.disposition_text (node: abc123...)"
  ],
  "embeddings_summary": {
    "expected": 8,
    "present": 7,
    "missing": 1
  }
}
```

---

## Related Documentation

- [GRAPH_VERSIONING.md](./GRAPH_VERSIONING.md) - Draft vs published data model
- [CASE_COMPARISON.md](./CASE_COMPARISON.md) - Postgres/Neo4j comparison logic
- [ADMIN_NEO4J_CASE_VIEW.md](./ADMIN_NEO4J_CASE_VIEW.md) - Admin view for Neo4j data

