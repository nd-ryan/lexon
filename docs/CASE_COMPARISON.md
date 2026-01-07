# Case Data Comparison (Postgres ↔ Neo4j)

This module provides reusable logic for comparing case data between Postgres and Neo4j.

---

## Purpose

The comparison module provides **three-part validation**:

1. **Sync Validation**: Ensures Neo4j correctly mirrors Postgres data
2. **Postgres Integrity**: Validates source data completeness (what admin can edit)
3. **Neo4j Integrity**: Validates knowledge graph completeness (the actual goal)

This design provides defense in depth - even if sync appears to work, the Neo4j integrity check confirms the KG actually has valid data.

---

## Three-Part Validation Architecture

| Validation | Question | Admin Action |
|------------|----------|--------------|
| **Sync** | Does Neo4j match Postgres? | Re-submit to KG |
| **Postgres Integrity** | Is source data complete? | Fix in case editor |
| **Neo4j Integrity** | Is the KG complete & valid? | Confirms fix worked |

### Scenarios

| Postgres | Sync | Neo4j | What it means | Admin action |
|----------|------|-------|---------------|--------------|
| Valid | Synced | Valid | Perfect! | None |
| Invalid | Synced | Invalid | Source issue | Fix in editor, re-submit |
| Valid | Out of sync | Invalid | Sync failed | Re-submit to KG |
| Invalid | Out of sync | Invalid | Both issues | Fix in editor, re-submit |

---

## How it works

### Comparison process

1. Fetch case data from Postgres (`kg_extracted` if available, else `extracted`)
2. Fetch case data from Neo4j (via Cypher query)
3. Both are in the same `{ nodes, edges }` format
4. Compare nodes by unique key (`temp_id` or `*_id` property)
5. Compare edges by unique key (`{from}:{to}:{label}`)
6. For each match, compare properties field-by-field

### Node matching

Nodes are matched by their unique identifier:
- Primary: `temp_id` field
- Fallback: Any property ending in `_id` (e.g., `case_id`, `proceeding_id`)

### Edge matching

Edges are matched by composite key:
- `{from}:{to}:{label}` (e.g., `uuid-1:uuid-2:HAS_PROCEEDING`)

### Property comparison

Properties are compared with normalization:
- Empty strings treated as `null`
- Embedding arrays (large float arrays) are skipped
- Internal fields are skipped: `temp_id`, `is_existing`, `status`, `source`, `preset`
- Fields ending in `_embedding` are skipped

### Type normalization

The comparison handles type differences between Postgres and Neo4j:

| Type | Postgres format | Neo4j format | Normalized to |
|------|----------------|--------------|---------------|
| Date | `"2006-11-28"` (ISO string) | `{_Date__ordinal: 732643, _Date__year: 2006, ...}` | ISO string |
| Time | `"14:30:00"` | `{_Time__hour: 14, _Time__minute: 30, ...}` | ISO string |
| DateTime | ISO string | `{_DateTime__year: ..., _DateTime__hour: ...}` | ISO string |

Neo4j stores dates/times as native `neo4j.time.*` objects. When serialized to JSON, these become dicts with internal Python attributes (`_Date__year`, `_Date__ordinal`, etc.). The comparison module detects these and converts them back to ISO strings for fair comparison.

### Catalog nodes (automatically skipped)

Certain node types are **catalog nodes** - shared/immutable entities that exist only in Neo4j:

| Label | Description |
|-------|-------------|
| Domain | Legal domain categories (e.g., Antitrust, IP) |
| Forum | Courts and tribunals |
| Jurisdiction | Geographic/legal jurisdictions |
| ReliefType | Types of relief (injunction, damages, etc.) |

These are identified from `schema_v3.json` by the combination:
- `case_unique: false` (shared across cases)
- `can_create_new: false` (users select from existing, can't create new)

**Why they're skipped:**
- Catalog nodes are intentionally stripped from Postgres before saving (to avoid duplication)
- Edges to catalog nodes are preserved in Postgres (the IDs are referenced)
- The frontend fetches catalog nodes separately via `useCatalogEnrichment`

The comparison automatically excludes these from the diff, but reports them in `summary.catalog_nodes_skipped`.

### Embedding validation

The comparison validates that Neo4j has embedding values for all properties that should have them.

**How it works:**
1. Schema defines which properties have `_embedding` counterparts (e.g., `name` → `name_embedding`)
2. Cypher query checks if each embedding property is NOT NULL (without returning the actual values)
3. Missing embeddings are reported in `summary.embeddings`

**Properties checked (derived from schema):**

| Label | Properties with embeddings |
|-------|---------------------------|
| Case | name, summary |
| Issue | text |
| Ruling | reasoning, ratio, summary |
| Argument | text, disposition_text |
| Relief | description |
| Doctrine | name, description |
| Policy | name, description |
| Law | name, text |
| FactPattern | name, description |
| Forum | name |

**Note:** Embedding values are NOT returned (they're too large). The check only verifies presence via `IS NOT NULL`.

### Required properties validation

The comparison validates that all required properties (as defined in `schema_v3.json`) are present in the extracted data. This identifies cases that uploaded successfully but are incomplete and need manual completion.

**How it works:**
1. Schema defines which properties are required via `"required": true` in the `ui` object
2. For each node, check that all required properties have non-empty values
3. Missing required properties are reported in `summary.required_properties`

**Required properties per label (derived from schema):**

| Label | Required properties |
|-------|---------------------|
| Case | name, citation, type, summary, status, outcome, court_level |
| Proceeding | stage, decided_date |
| Issue | label, text, type |
| Forum | name, type |
| Jurisdiction | name |
| Domain | name |
| Party | name, type |
| Ruling | label, type, reasoning, ratio, summary |
| Doctrine | name, description |
| Policy | name, description |
| Argument | label, text, disposition_text, raised_by |
| Relief | description |
| ReliefType | type |
| Law | name, text, type, citation |
| FactPattern | name, description |

**Use case:** The AI extraction process may leave some required properties empty (intentionally, to avoid hallucination). The comparison flags these cases as "needs completion" so admins can manually fill in the missing data.

### Required relationships validation

The comparison validates that all required relationships (as defined in `schema_v3.json`) exist. This identifies nodes that are missing expected connections.

**Schema fields for relationships:**

| Field | Meaning |
|-------|---------|
| `required` | Source node must have at least one outgoing relationship of this type |
| `min` | Minimum count of outgoing edges required (default: 1) |
| `inverse_required` | Target node must have at least one incoming relationship of this type |
| `inverse_min` | Minimum count of incoming edges required on target (default: 1) |

**Example from schema:**

```json
"Argument": {
  "relationships": {
    "EVALUATED_IN": {
      "target": "Ruling",
      "cardinality": "many-to-many",
      "required": true,           // Argument must have outgoing EVALUATED_IN
      "min": 1,
      "inverse_required": true,   // Ruling must have incoming EVALUATED_IN
      "inverse_min": 1
    }
  }
}
```

**How it works:**
1. Parse schema for relationships with `required: true` (outgoing) and `inverse_required: true` (incoming)
2. For each node, count its outgoing/incoming edges of each required type
3. Flag if count < `min` or count < `inverse_min`

### Relationship properties validation

The comparison validates that required properties on relationships have values.

**How it works:**
1. Schema defines relationship properties with `ui.required: true`
2. For each edge with required properties, check they have non-empty values
3. Missing relationship properties are reported in `summary.relationship_properties`

**Example relationship with required property:**

```json
"INVOLVES": {
  "target": "Party",
  "properties": {
    "role": { "type": "STRING", "ui": { "required": true, ... } }
  }
}
```

### Cardinality validation

The comparison validates that relationship cardinality constraints are respected.

**Cardinality types:**

| Type | Source constraint | Target constraint |
|------|------------------|-------------------|
| `one-to-one` | At most 1 outgoing edge | Each target referenced at most once |
| `one-to-many` | No limit | Each target referenced at most once |
| `many-to-one` | At most 1 outgoing edge | No limit |
| `many-to-many` | No limit | No limit |

**Violations reported:**
- `source_multiple`: Source has more outgoing edges than allowed
- `target_multiple`: Target referenced by more sources than allowed

---

## Comparison statuses

| Status | Meaning |
|--------|---------|
| `match` | Node/edge exists in both with identical properties |
| `differ` | Node/edge exists in both but properties differ |
| `only_postgres` | Node/edge exists only in Postgres |
| `only_neo4j` | Node/edge exists only in Neo4j |

---

## API response structure

```json
{
  "success": true,
  "postgres_case_id": "uuid",
  "neo4j_case_id": "uuid",
  "all_match": false,
  "needs_completion": true,
  "summary": {
    "sync": {
      "all_synced": true,
      "nodes": {
        "total_postgres": 15,
        "total_neo4j": 15,
        "match": 15,
        "differ": 0,
        "only_postgres": 0,
        "only_neo4j": 0
      },
      "edges": {
        "total_postgres": 20,
        "total_neo4j": 20,
        "match": 20,
        "differ": 0,
        "only_postgres": 0,
        "only_neo4j": 0
      },
      "catalog_nodes_skipped": {
        "total": 4,
        "by_label": { "Domain": 1, "Forum": 1, "Jurisdiction": 1, "ReliefType": 1 },
        "labels": ["Domain", "Forum", "Jurisdiction", "ReliefType"]
      }
    },
    "postgres_integrity": {
      "all_valid": false,
      "required_properties": {
        "total_expected": 45,
        "total_present": 43,
        "total_missing": 2,
        "all_present": false,
        "missing": [
          { "node_id": "ruling-123", "label": "Ruling", "property": "ratio" }
        ]
      },
      "required_relationships": {
        "total_expected": 10,
        "total_present": 9,
        "total_missing": 1,
        "all_present": false,
        "missing": [
          { "node_id": "ruling-789", "label": "Ruling", "relationship": "SETS", "direction": "outgoing", "expected_min": 1, "actual_count": 0 }
        ]
      },
      "relationship_properties": {
        "total_expected": 5,
        "total_present": 5,
        "total_missing": 0,
        "all_present": true,
        "missing": []
      },
      "cardinality": {
        "total_violations": 0,
        "all_valid": true,
        "violations": []
      }
    },
    "neo4j_integrity": {
      "all_valid": false,
      "required_properties": {
        "total_expected": 45,
        "total_present": 43,
        "total_missing": 2,
        "all_present": false,
        "missing": [
          { "node_id": "ruling-123", "label": "Ruling", "property": "ratio" }
        ]
      },
      "required_relationships": {
        "total_expected": 10,
        "total_present": 9,
        "total_missing": 1,
        "all_present": false,
        "missing": [
          { "node_id": "ruling-789", "label": "Ruling", "relationship": "SETS", "direction": "outgoing", "expected_min": 1, "actual_count": 0 }
        ]
      },
      "relationship_properties": {
        "total_expected": 5,
        "total_present": 5,
        "total_missing": 0,
        "all_present": true,
        "missing": []
      },
      "cardinality": {
        "total_violations": 0,
        "all_valid": true,
        "violations": []
      },
      "embeddings": {
        "total_expected": 12,
        "total_present": 11,
        "total_missing": 1,
        "all_present": false,
        "missing": [
          { "node_id": "ruling-123", "label": "Ruling", "property": "ratio" }
        ]
      }
    }
  },
  "node_comparisons": [
    {
      "node_id": "uuid",
      "label": "Case",
      "status": "differ",
      "differences": [
        {
          "field": "name",
          "postgres_value": "Smith v. Jones",
          "neo4j_value": "Smith vs Jones"
        }
      ]
    }
  ],
  "edge_comparisons": [
    {
      "edge_id": "from:to:label",
      "label": "HAS_PROCEEDING",
      "from": "uuid-1",
      "to": "uuid-2",
      "status": "match",
      "differences": []
    }
  ]
}
```

---

## Key files

### Backend

| File | Purpose |
|------|---------|
| `ai-backend/app/lib/case_comparison.py` | Core comparison logic (reusable) |
| `ai-backend/app/routes/neo4j_cases.py` | API endpoint (`GET /{neo4j_case_id}/compare`) |

### Core functions

**`compare_case_data(postgres_data, neo4j_data, schema=None)`**
- Main entry point
- Takes two `{ nodes, edges }` dicts
- Optionally accepts schema to determine catalog nodes (loads from file if not provided)
- Automatically filters out catalog nodes from Neo4j data before comparison
- Returns full comparison result

**`get_catalog_node_labels(schema=None)`**
- Returns set of label strings for catalog-only nodes
- Derives from schema: `case_unique=false` AND `can_create_new=false`
- Used to filter out nodes that are intentionally not stored in Postgres

**`get_required_properties_config(schema=None)`**
- Returns dict of `{label: [required_prop_names...]}` for properties that must have values
- Derives from schema: `ui.required=true`
- Excludes internal fields (`*_id`, `*_embedding`, `*_upload_code`)

**`check_missing_required_properties(nodes, schema=None)`**
- Validates that all required properties have non-empty values
- Returns summary with missing required properties list
- Used to identify cases that need manual completion

**`get_required_relationships_config(schema=None)`**
- Returns config for required relationships: `{outgoing: {...}, incoming: {...}}`
- Parses `required`, `min`, `inverse_required`, `inverse_min` from schema
- Used to identify nodes missing required connections

**`check_missing_required_relationships(nodes, edges, schema=None)`**
- Validates that required relationships exist for all nodes
- Checks both outgoing (`required: true`) and incoming (`inverse_required: true`)
- Returns summary with missing relationships list

**`check_relationship_properties(edges, nodes, schema=None)`**
- Validates that required properties on relationships have values
- Parses relationship properties with `ui.required: true` from schema
- Returns summary with missing relationship properties list

**`check_cardinality_violations(nodes, edges, schema=None)`**
- Validates cardinality constraints on relationships
- Checks one-to-one, one-to-many, many-to-one constraints
- Returns summary with violation details

**`get_embedding_config(schema=None)`**
- Returns dict of `{label: [prop_names...]}` for properties that should have embeddings
- Derives from schema: property `p` if `p` is STRING type and `p_embedding` exists

**`check_neo4j_embeddings(neo4j_client, case_nodes, schema=None)`**
- Validates embedding presence in Neo4j for specific case nodes only
- Takes the filtered list of nodes (not a case_id) to ensure only this case's data is checked
- Uses Cypher `IS NOT NULL` checks for efficiency
- Returns summary with missing embeddings list

**`_compare_nodes(postgres_nodes, neo4j_nodes)`**
- Compares node lists
- Returns `(comparisons, stats)`

**`_compare_edges(postgres_edges, neo4j_edges)`**
- Compares edge lists
- Returns `(comparisons, stats)`

**`_compare_properties(pg_props, neo_props, skip_fields)`**
- Compares property dicts
- Returns list of differences

---

## Usage examples

### Direct usage (for upload validation)

```python
from app.lib.case_comparison import compare_case_data

# Both should be { nodes: [...], edges: [...] } format
postgres_data = {"nodes": [...], "edges": [...]}
neo4j_data = {"nodes": [...], "edges": [...]}

result = compare_case_data(postgres_data, neo4j_data)

if result["all_match"]:
    print("Data is in sync!")
else:
    print(f"Found {result['summary']['nodes']['differ']} node differences")
    print(f"Found {result['summary']['edges']['differ']} edge differences")
```

### Via API endpoint

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/ai/neo4j-cases/{neo4j_case_id}/compare?postgres_case_id={pg_id}"
```

---

## Integration points

### 1. Admin Neo4j View (Single Case)

The comparison is triggered on-demand from the admin Neo4j case view page:
- See [ADMIN_NEO4J_CASE_VIEW.md](./ADMIN_NEO4J_CASE_VIEW.md)

### 2. Batch Comparison (Case List Page)

Admins can run comparisons across all cases from the case list page:

**UI Features:**
- "Run Comparisons" button (admin-only, top right of case list)
- Live progress modal with SSE updates
- Filter cases by comparison status (Issues, Synced, Pending, etc.)
- Comparison status badges on each case row
- Clickable amber warnings link to the Neo4j comparison page

**Comparison Status Values:**

| Status | Meaning | Display |
|--------|---------|---------|
| `not_in_kg` | Never submitted to KG | Gray "Not in KG" |
| `pending` | Postgres updated after last KG submit | Blue "Pending sync" |
| `not_checked` | In KG but comparison never run | Gray "Not checked" |
| `synced` | Comparison passed (`all_match=true`, no missing required) | Green "✓ Synced" |
| `needs_completion` | Synced correctly but missing required properties | Orange "📝 X required fields missing" |
| `issues` | Comparison found sync differences | Amber "⚠ X fields, Y embeddings" |

**Smart Staleness Detection:**

Comparisons are cached in Postgres (`case_comparisons` table). A comparison is considered stale and will re-run if:
- Postgres `updated_at` > comparison `compared_at`
- KG `kg_submitted_at` > comparison `compared_at`

Use "Force Re-run All" to bypass staleness checks.

### 3. Auto-Comparison After KG Submit

When a case is successfully submitted to the Knowledge Graph, a comparison job is automatically queued:

```python
# In kg.py after successful upload
from app.lib.queue import comparison_queue
from app.jobs.comparison_job import compare_single_case

comparison_queue.enqueue(compare_single_case, case_id, True)  # force=True
```

This ensures comparison results are always up-to-date after KG uploads.

---

## Batch Comparison API

### Start Batch Comparison

```bash
POST /api/admin/comparisons/batch
Content-Type: application/json

{
  "case_ids": null,  // null = all KG-submitted cases
  "force": false     // force re-run even if fresh
}
```

Response:
```json
{
  "job_id": "uuid",
  "queued_count": 42,
  "message": "Queued 42 cases for comparison"
}
```

### Stream Progress (SSE)

```bash
GET /api/admin/comparisons/progress/{job_id}
Accept: text/event-stream
```

Events:
- `{"type": "progress", "completed": 5, "total": 42, "current_case": "Smith v. Jones"}`
- `{"type": "complete", "total": 42, "success_count": 40, "fail_count": 2}`
- `{"type": "error", "message": "..."}`

### Get Single Comparison Result

```bash
GET /api/admin/comparisons/{case_id}
```

### Force Re-run Single Comparison

```bash
POST /api/admin/comparisons/{case_id}
Content-Type: application/json

{"force": true}
```

---

## Key Files (Batch Comparison)

| File | Purpose |
|------|---------|
| `ai-backend/app/lib/schema.py` | `case_comparisons` table schema |
| `ai-backend/app/lib/comparison_repo.py` | CRUD operations for comparison results |
| `ai-backend/app/jobs/comparison_job.py` | Background job for batch comparisons |
| `ai-backend/app/routes/comparisons.py` | Admin API endpoints |
| `src/app/api/admin/comparisons/*` | Next.js proxy routes (admin-protected) |
| `src/app/cases/page.tsx` | Case list UI with comparison features |

---

## Notes

- **Three-part validation**: The comparison provides sync check, Postgres integrity, AND Neo4j integrity (defense in depth)
- **Performance**: Comparison is O(n) where n = total nodes + edges
- **Embeddings excluded from property comparison**: Large embedding arrays are automatically excluded from property diffs
- **Embedding validation**: Checks that Neo4j has embedding values (without returning the values)
- **Required properties validation**: Checks that all required properties have non-empty values (identifies incomplete extractions)
- **Required relationships validation**: Checks that required relationships exist (schema fields: `required`, `min`, `inverse_required`, `inverse_min`)
- **Relationship properties validation**: Checks that required properties on relationships have values
- **Cardinality validation**: Checks that relationship cardinality constraints (one-to-one, one-to-many, etc.) are respected
- **String normalization**: Empty strings are treated as null for comparison
- **Type normalization**: Neo4j date/time objects are converted to ISO strings to match Postgres format
- **Catalog nodes**: Automatically derived from schema and excluded from comparison (reported separately)
- **Order-independent**: Node/edge order doesn't affect comparison results
- **Needs completion status**: Cases where Neo4j integrity has issues show "📝 Needs completion"
- **Extraction flow warnings**: During extraction (Phase 10), missing required relationships are logged as non-blocking warnings
- **Neo4j integrity as source of truth**: The `needs_completion` flag is based on Neo4j integrity, not Postgres - confirming the KG actually has valid data

