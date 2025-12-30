# Case Data Comparison (Postgres ↔ Neo4j)

This module provides reusable logic for comparing case data between Postgres and Neo4j.

---

## Purpose

The comparison module is designed for:

1. **Admin validation**: On-demand comparison from the Neo4j case view page
2. **Upload validation**: Automatic validation during KG upload (future use)
3. **Data integrity checks**: Verifying sync between data stores

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
- Internal fields are skipped: `temp_id`, `is_existing`, `status`, `source`
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
  "summary": {
    "nodes": {
      "total_postgres": 15,
      "total_neo4j": 15,
      "match": 14,
      "differ": 1,
      "only_postgres": 0,
      "only_neo4j": 0
    },
    "edges": {
      "total_postgres": 20,
      "total_neo4j": 20,
      "match": 18,
      "differ": 2,
      "only_postgres": 0,
      "only_neo4j": 0
    },
    "catalog_nodes_skipped": {
      "total": 4,
      "by_label": {
        "Domain": 1,
        "Forum": 1,
        "Jurisdiction": 1,
        "ReliefType": 1
      },
      "labels": ["Domain", "Forum", "Jurisdiction", "ReliefType"]
    },
    "embeddings": {
      "total_expected": 12,
      "total_present": 11,
      "total_missing": 1,
      "all_present": false,
      "missing": [
        {
          "node_id": "ruling-123",
          "label": "Ruling",
          "property": "ratio"
        }
      ]
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

### Current: Admin Neo4j View

The comparison is triggered on-demand from the admin Neo4j case view page:
- See [ADMIN_NEO4J_CASE_VIEW.md](./ADMIN_NEO4J_CASE_VIEW.md)

### Future: KG Upload Validation

The `compare_case_data()` function can be called after KG upload to validate:

```python
# In kg.py after successful upload
from app.lib.case_comparison import compare_case_data

# ... after upload completes ...
result = compare_case_data(postgres_extracted, neo4j_extracted)
if not result["all_match"]:
    logger.warning(f"KG upload validation failed: {result['summary']}")
    # Could return warning to user or trigger retry
```

---

## Notes

- **Performance**: Comparison is O(n) where n = total nodes + edges
- **Embeddings excluded from property comparison**: Large embedding arrays are automatically excluded from property diffs
- **Embedding validation**: Checks that Neo4j has embedding values (without returning the values)
- **String normalization**: Empty strings are treated as null for comparison
- **Type normalization**: Neo4j date/time objects are converted to ISO strings to match Postgres format
- **Catalog nodes**: Automatically derived from schema and excluded from comparison (reported separately)
- **Order-independent**: Node/edge order doesn't affect comparison results

