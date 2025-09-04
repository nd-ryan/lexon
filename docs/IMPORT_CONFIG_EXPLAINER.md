# Import Configuration: Inputs and Updates

A concise reference for what the import relies on and what it updates.

## A) Config the import relies on

- **AI backend and security**
  - `AI_BACKEND_URL`: Base URL for FastAPI (default `http://localhost:8000`). Used by Next.js API route `src/app/api/import-kg/route.ts` to proxy uploads.
  - `FASTAPI_API_KEY`: Sent as `X-API-Key` by the Next.js route; validated by FastAPI.
- **Neo4j connection**
  - `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`: Used by `ai-backend/app/lib/neo4j_client.py`.
- **OpenAI**
  - `OPENAI_API_KEY`: Enables embeddings in `ai-backend/app/lib/embeddings.py`.
- **Cached schema helpers (read at start of processing)**
  - `ai-backend/relationship_mappings.json`: Seed of `(FromLabel)->(ToLabel)` → `[REL_TYPE]` mappings, loaded then merged with live Neo4j.
  - `ai-backend/property_mappings.json`: Used by utilities (e.g., `batch_query_utils`) for known `id_properties` and `name_properties`.
- **EMBEDDING_CONFIG in embeddings.py**
  - Hard-coded list of properties to create embeddings for. 

## B) Config the import updates (and why)

- `ai-backend/relationship_mappings.json`
  - When: During processing (schema alignment).
  - How: Extracts current relationship types from Neo4j, merges with cached, writes back via `_save_relationship_constraints()` in `ai-backend/app/lib/dynamic_document_processor.py`.
  - Why: Caches live constraints to improve alignment in future imports.

- `ai-backend/property_mappings.json`
  - When: After a successful import completes.
  - How: `_update_property_mappings_after_import()` fetches schema (via MCP), uses AI to categorize properties into `id_properties` and `name_properties`; falls back to direct Neo4j queries if needed.
  - Why: Maintains an up-to-date view of identifier and name fields for search, display, and import heuristics.

- Neo4j node embeddings (not a file)
  - When: After data insertion (whole document and per-case paths).
  - How: `generate_embeddings_for_nodes()` writes vectors as `<property>_embedding` on nodes.
  - Why: Enables semantic/embedding-powered features without a separate pipeline.

Notes:
- Relationship mappings update earlier (to aid alignment mid-run); property mappings update later (post-success, to inform future runs and UI).
- If `OPENAI_API_KEY` is unset, embeddings are skipped gracefully.
