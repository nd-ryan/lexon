# Backend Test Suite Manifest

## Overview

This document provides a centralized reference for all backend tests, organized by test file and category.

**Total Tests:** 151  
**Test Framework:** pytest with async support  
**Coverage Areas:** Case extraction flow (V3), shared nodes management, preset node behavior, graph event logging, Neo4j uploader helpers, optional Neo4j/Search integration checks, API security  
**Pass Rate:** 100% ✅

---

## Test Files

### 1. `test_neo4j_uploader_transaction_atomicity.py` - Neo4j Upload Atomicity (2 tests)

**Purpose:** Ensures KG submit/upload cannot partially commit to Neo4j: all node + edge writes are wrapped in a single Neo4j transaction and rolled back on any failure.

**What it covers:**
- Edge write failure triggers rollback (no commit)
- Successful run commits

---

### 2. `conftest.py` - Shared Test Fixtures

**Purpose:** Provides reusable fixtures and mock objects for all test files.

**Fixtures:**
- `sample_schema` - Test schema data (subset of schema_v3.json)
- `mock_neo4j_client` - Mocked Neo4j client for graph operations
- `mock_db_connection` - Mocked database connection
- `mock_db_session` - Mocked SQLAlchemy session
- `async_client` - FastAPI test client with auth/DB overrides
- `api_key_header` - API key header for authenticated requests
- `user_id_header` - User ID header for attribution
- `sample_node_data` - Sample node properties for testing
- `sample_case_data` - Sample case data with extracted JSON

---

## 2. `test_shared_nodes.py` - Shared Node Management (58 tests)

### Helper Function Tests (20 tests)

#### `TestGetIdProperty` (5 tests)
Tests snake_case conversion of node labels to ID property names.

- **test_simple_label** - Converts "Party" → "party_id"
- **test_camelcase_label** - Converts "ReliefType" → "relief_type_id"
- **test_multi_word_label** - Converts "FactPattern" → "fact_pattern_id"
- **test_single_word_label** - Converts "Case" → "case_id"
- **test_domain_label** - Converts "Domain" → "domain_id"

#### `TestGetSharedLabels` (4 tests)
Tests filtering of schema to extract shared (non-case-unique) node labels.

- **test_filters_case_unique_false** - Returns only labels with case_unique=false
- **test_excludes_case_unique_true** - Excludes case_unique=true labels
- **test_empty_schema** - Handles empty schema gracefully
- **test_handles_non_dict_items** - Filters out invalid schema entries

#### `TestGetMinPerCase` (3 tests)
Tests retrieval of minimum node count requirement per case from schema.

- **test_returns_configured_value** - Returns min_per_case value when set
- **test_returns_zero_when_not_set** - Defaults to 0 when not configured
- **test_returns_zero_for_unknown_label** - Returns 0 for non-existent labels

#### `TestGetNodeDisplayName` (6 tests)
Tests extraction of human-readable display name from node properties.

- **test_uses_name_property** - Uses "name" property as primary choice
- **test_uses_label_property** - Falls back to "label" property
- **test_uses_type_property** - Falls back to "type" property
- **test_truncates_long_names** - Truncates names > 100 chars with "..."
- **test_fallback_to_label** - Uses node label when no display property exists
- **test_unknown_label_fallback** - Returns "Unknown" as last resort

#### `TestGetUserId` (3 tests)
Tests extraction of user ID from X-User-Id request header.

- **test_extracts_from_header** - Extracts user ID from header
- **test_default_when_missing** - Defaults to "admin" when header missing
- **test_default_when_empty** - Defaults to "admin" when header empty

#### `TestFindCasesContainingNode` (3 tests)
Tests lookup of cases containing a specific shared node via Postgres.

- **test_extracts_case_name_from_extracted** - Parses case name from extracted JSON
- **test_fallback_to_filename** - Uses filename when case name not found
- **test_counts_labels_correctly** - Counts instances of node label in case

#### `TestGetCaseNodeIds` (3 tests)
Tests extraction of all node IDs from a case's node list.

- **test_extracts_all_ids** - Extracts all *_id properties from nodes
- **test_handles_missing_properties** - Handles nodes without properties
- **test_handles_non_dict_nodes** - Filters out invalid node entries

### API Endpoint Tests (26 tests + 11 preset node tests)

#### `TestListSharedNodesEndpoint` (4 tests)
Tests `GET /api/ai/shared-nodes` endpoint for listing shared nodes.

- **test_requires_api_key** - Returns 403 when API key missing
- **test_returns_nodes_list** - Returns paginated list of shared nodes
- **test_filters_by_label** - Filters nodes by label parameter
- **test_rejects_case_unique_label** - Returns 400 for case_unique labels

#### `TestGetSharedNodeEndpoint` (2 tests)
Tests `GET /api/ai/shared-nodes/{label}/{node_id}` for node details.

- **test_returns_node_details** - Returns node with connected cases
- **test_returns_404_for_missing_node** - Returns 404 when node not found

#### `TestUpdateSharedNodeEndpoint` (3 tests)
Tests `PUT /api/ai/shared-nodes/{label}/{node_id}` for updating nodes.

- **test_updates_node_properties** - Updates node properties in Neo4j
- **test_rejects_protected_properties** - Rejects updates to *_id properties
- **test_logs_update_events** - Logs update events for each connected case

#### `TestDeleteSharedNodeEndpoint` (10 tests)
Tests `DELETE /api/ai/shared-nodes/{label}/{node_id}` for node deletion with catalog node preservation.

- **test_deletes_node_fully** - Deletes node when no min_per_case violations
- **test_returns_min_per_case_violation** - Returns error when deletion violates min_per_case
- **test_partial_delete_with_force** - Performs partial deletion with force_partial flag
- **test_logs_delete_events** - Logs delete events for affected cases
- **test_returns_404_for_missing_node** - Returns 404 when node not found
- **test_catalog_node_detached_not_deleted_when_connected** - Catalog nodes are detached but preserved in KG ✨
- **test_orphaned_catalog_node_can_be_deleted** - Orphaned catalog nodes can be fully deleted ✨
- **test_non_catalog_node_deleted_after_detachment** - Non-catalog shared nodes are detached from cases and preserved in KG ✨ *(test name is misleading)*
- **test_min_per_case_error_prevents_any_deletion** - No deletion occurs when min_per_case violated ✨
- **test_detachment_removes_only_case_relationships** - Detachment only removes relationships to specific case nodes ✨
- **(behavior note)** - Detachment also removes the node reference from Postgres `cases.extracted` (authoritative case membership) ✨

#### `TestPresetNodeBehavior` (7 tests) ✨NEW
Tests behavior for preset nodes (canonical nodes uploaded by legal experts).

- **test_list_nodes_returns_is_preset** - Returns isPreset=true for preset nodes in list
- **test_list_nodes_returns_is_preset_false** - Returns isPreset=false for non-preset nodes
- **test_get_node_returns_is_preset** - Returns isPreset field in single node response
- **test_orphaned_preset_node_preserved** - Orphaned preset nodes are preserved (not deleted) by default
- **test_orphaned_preset_node_force_deleted** - Orphaned preset nodes can be force-deleted with force_delete=true
- **test_orphaned_non_preset_node_auto_deleted** - Orphaned non-preset nodes are auto-deleted

#### `TestPresetToggleEndpoint` (4 tests) ✨NEW
Tests `PATCH /api/ai/shared-nodes/{label}/{node_id}/preset` for toggling preset status.

- **test_set_preset_true** - Sets preset=true on a node
- **test_set_preset_false** - Removes preset property from a node
- **test_toggle_preset_404_for_missing_node** - Returns 404 when node not found

---

## 3. `test_case_delete_kg_cleanup.py` - Case Deletion KG Cleanup (5 tests)

**Purpose:** Validates Neo4j cleanup behavior when deleting a case (`DELETE /api/ai/cases/{case_id}`) for KG-submitted cases.

**What it covers:**
- Neo4j cleanup is skipped when `kg_submitted_at` is null (draft cases never wrote to KG)
- Shared nodes and `is_existing` nodes are detached (preserved) during case deletion
- 404 when deleting a missing case
- **Case-unique nodes** (`case_unique: true`) are deleted from Neo4j only if **isolated** to the case; otherwise they are **detached** (defensive safety).

---

## 4. `test_kg_submit_deletion_policy.py` - KG Submit Deletion Policy (2 tests)

**Purpose:** Validates deletion side-effects during KG submit (`POST /api/ai/kg/submit`) without running the full KG flow.

**What it covers:**
- Deleted shared nodes (`case_unique: false`) are detached from the case (preserved), not globally deleted
- Deleted case-unique nodes (`case_unique: true`) are deleted only when isolated to the case

---

## 5. `test_kg_submit_event_logging.py` - KG Submit Event Logging (2 tests)

**Purpose:** Validates that `graph_events` are emitted on KG submit based on the last published snapshot (`cases.kg_extracted`), not on draft saves.

**What it covers:**
- On subsequent KG submit, removals from the published graph produce `delete` events
- On first publish, `is_existing` nodes do not emit node-level `create` events (edge events still log)

---

## 6. `test_cases_get_case_does_not_expose_kg_extracted.py` - Cases API Response Shape (1 test)

**Purpose:** Ensures internal published snapshot fields (e.g. `cases.kg_extracted`) are not returned to clients via `GET /api/ai/cases/{case_id}`.

---

## 7. `test_graph_events_repo.py` - Event Logging (30 tests)

### Helper Function Tests (6 tests)

#### `TestComputeContentHash` (6 tests)
Tests deterministic hashing of node/edge properties for change tracking.

- **test_deterministic_hash** - Same input produces same hash
- **test_different_key_order_same_hash** - Key order doesn't affect hash
- **test_different_values_different_hash** - Different values produce different hashes
- **test_empty_dict** - Handles empty dictionary
- **test_nested_objects** - Handles nested dictionaries
- **test_handles_non_json_types** - Converts non-JSON types via str()

#### `TestMakeEdgeId` (3 tests)
Tests creation of composite edge IDs in "from:to:label" format.

- **test_creates_composite_key** - Creates correct format
- **test_handles_uuids** - Handles UUID strings correctly
- **test_handles_colons_in_label** - Handles edge labels containing colons

### Repository Method Tests (24 tests)

#### `TestGraphEventsRepoLogEvent` (3 tests)
Tests core event logging functionality.

- **test_inserts_event_record** - Inserts event into graph_events table
- **test_returns_event_id** - Returns valid UUID string
- **test_computes_content_hash** - Computes hash from properties

#### `TestGraphEventsRepoLogNodeEvent` (2 tests)
Tests node-specific event logging wrapper.

- **test_sets_entity_type_to_node** - Sets entity_type="node"
- **test_passes_properties_and_changes** - Passes properties and property_changes

#### `TestGraphEventsRepoLogEdgeEvent` (2 tests)
Tests edge-specific event logging wrapper.

- **test_sets_entity_type_to_edge** - Sets entity_type="edge"
- **test_creates_composite_entity_id** - Creates from:to:label entity_id

#### `TestGraphEventsRepoGetEventsForCase` (2 tests)
Tests retrieval of all events for a specific case.

- **test_returns_events_list** - Returns list of events for case
- **test_orders_by_created_at_desc** - Orders events newest first

#### `TestGraphEventsRepoListEvents` (6 tests)
Tests querying events with various filters.

- **test_no_filters_returns_all** - Returns all events when unfiltered
- **test_filter_by_case_id** - Filters by case_id parameter
- **test_filter_by_user_id** - Filters by user_id parameter
- **test_filter_by_action** - Filters by action type (create/update/delete)
- **test_filter_by_entity_type** - Filters by entity_type (node/edge)
- **test_pagination** - Applies limit and offset parameters

#### `TestGraphEventsRepoGetEventStats` (1 test)
Tests aggregation of event statistics.

- **test_returns_stats_structure** - Returns total, by_action, and top_users

#### `TestGraphEventsRepoUpdateEntityIds` (8 tests)
Tests mapping of temporary node IDs to permanent Neo4j UUIDs.

- **test_maps_node_ids** - Updates node entity_ids with new UUIDs
- **test_maps_edge_ids** - Updates edge entity_ids (from:to:label format)
- **test_handles_partial_mapping** - Only updates IDs that have mappings
- **test_empty_mapping_returns_zero** - Returns 0 for empty mapping
- **test_no_matching_events_returns_zero** - Returns 0 when no events match

---

## 8. `test_case_extract_flow_v3_*.py` - Case Extraction Flow V3 (10 tests)

**Purpose:** Validates orchestration of the crucial [`app/flow_cases/case_extract_flow_v3.py`](../app/flow_cases/case_extract_flow_v3.py) workflow using **light integration** (real schema/validation code, deterministic mocked CrewAI + Neo4j).

**Files:**
- `test_case_extract_flow_v3_phases.py` (6 tests) - Phase 0–3 orchestration (schema prep, foundation extraction, forum selection, party extraction)
- `test_case_extract_flow_v3_helpers.py` (3 tests) - Unit tests for parsing/validation helpers used by the flow
- `test_case_extract_flow_v3_golden.py` (1 test) - Small “golden” shape test (phases 0–3 + `validate_case_graph`)

**Fixtures/Helpers:**
- `fixtures/case_extract_schema_min.json` - Minimal schema payload used for deterministic tests
- `_case_extract_test_utils.py` - Small test-only stubs for CrewAI outputs

---

## 9. `test_cardinality_validation.py` - Cardinality Validation (11 tests)

**Purpose:** Validates relationship cardinality enforcement in `app/lib/schema_runtime.py`.

**Key tests:**
- **TestValidateCardinality** - Unit tests for `_validate_cardinality()` helper
  - `test_one_to_one_valid` - Valid one-to-one relationships pass
  - `test_one_to_one_source_violation` - Detects when source has multiple edges
  - `test_one_to_one_target_violation` - Detects when target is referenced multiple times
  - `test_one_to_many_valid` - Valid one-to-many relationships pass
  - `test_one_to_many_target_violation` - Detects when target is reused in one-to-many
  - `test_many_to_one_valid` - Valid many-to-one relationships pass
  - `test_many_to_one_source_violation` - Detects when source has multiple edges
  - `test_many_to_many_no_restrictions` - Many-to-many has no restrictions
  - `test_unknown_cardinality_defaults_to_many_to_many` - Unknown defaults to no restrictions

- **TestValidateCaseGraphWithCardinality** - Integration tests with real schema
  - `test_ruling_sets_issue_one_to_one_enforced` - Verifies Ruling→SETS→Issue is one-to-one
  - `test_case_has_proceeding_one_to_many_allows_multiple` - Verifies Case→HAS_PROCEEDING is one-to-many

---

## 10. `test_neo4j_uploader.py` - Neo4j Uploader Helpers (2 tests)

**Purpose:** Validates helper utilities in `app/lib/neo4j_uploader.py` (e.g., snake_case conversion and ID property mapping).

---

## 11. `test_external_api_isolation.py` - External API Security (16 tests)

**Purpose:** Validates security isolation of the external API from internal routes.

**What it covers:**

#### `TestExternalCannotAccessInternal` (2 tests)
- **test_external_key_rejected_on_internal_route** - External API key rejected on /api/ai/* routes
- **test_external_key_rejected_on_internal_v1_route** - External API key rejected on /api/v1/* routes

#### `TestInternalCannotAccessExternal` (1 test)
- **test_internal_key_rejected_on_external_route** - Internal FASTAPI_API_KEY rejected on /external/v1/*

#### `TestEdgeSecretRequired` (2 tests)
- **test_missing_edge_secret_rejected** - Requests without X-Lexon-Edge header rejected
- **test_wrong_edge_secret_rejected** - Requests with wrong edge secret rejected

#### `TestHealthAndVersionNoAuth` (2 tests)
- **test_health_no_auth_required** - /health endpoint works without auth
- **test_version_no_auth_required** - /version endpoint works without auth

#### `TestOpenAPISpecRequiresAuth` (3 tests) ✨NEW
- **test_openapi_without_auth_rejected** - /openapi.json requires authentication
- **test_openapi_with_wrong_key_rejected** - /openapi.json rejects invalid API key
- **test_openapi_with_valid_auth_returns_spec** - /openapi.json returns valid spec with auth

#### `TestMultiKeyRotation` (2 tests)
- **test_first_key_works** - First key in LEXON_API_KEYS accepted
- **test_second_key_works** - Second key in LEXON_API_KEYS accepted

#### `TestRequestValidation` (3 tests)
- **test_extra_fields_rejected** - Unknown fields in request body rejected
- **test_query_too_long_rejected** - Query exceeding max_length rejected
- **test_empty_query_rejected** - Empty query rejected

#### `TestQueryLogging` (1 test)
- **test_query_content_not_in_logs** - Sensitive query content never appears in logs

---

## 12. Integration Tests (optional / external dependencies)

These are marked with `@pytest.mark.integration` and are **skipped** unless required environment variables are present.

**Neo4j driver direct checks:**
- `test_neo4j_integration_direct.py` (3 tests)

**Neo4j client wrapper checks:**
- `test_neo4j_integration_client.py` (2 tests)

**Doctrine query shape check:**
- `test_doctrine_query_integration.py` (1 test)

**Full SearchFlow end-to-end (very heavyweight):**
- `test_search_flow_integration.py` (1 test) - additionally requires `RUN_SEARCH_FLOW_INTEGRATION=1`

---

## Running Tests

### All Backend Tests
```bash
cd ai-backend
poetry run pytest -v
```

### Specific Test File
```bash
cd ai-backend
poetry run pytest tests/test_shared_nodes.py -v
```

```bash
cd ai-backend
poetry run pytest tests/test_case_delete_kg_cleanup.py -v
```

```bash
cd ai-backend
poetry run pytest tests/test_kg_submit_deletion_policy.py -v
```

### Exclude Integration Tests
```bash
cd ai-backend
poetry run pytest -m "not integration" -v
```

### Run Only Integration Tests
```bash
cd ai-backend
poetry run pytest -m integration -v
```

### With Coverage
```bash
cd ai-backend
make test-cov
```

### Single Test
```bash
cd ai-backend
poetry run pytest tests/test_shared_nodes.py::TestGetIdProperty::test_simple_label -v
```

---

## Test Strategy

### Mocking Approach
- **Neo4j:** Fully mocked via `monkeypatch.setattr()`
- **Postgres:** Mocked SQLAlchemy session with MagicMock
- **API Key Auth:** Dependency override in FastAPI test client
- **External Services:** No real connections required

### Coverage Goals
- ✅ Helper function unit tests (pure logic)
- ✅ API endpoint integration tests (auth, validation, business logic)
- ✅ Event logging integration tests (database operations)
- ✅ Error handling and edge cases

### Key Testing Patterns

**1. Helper Function Tests:**
```python
def test_simple_label(self):
    from app.routes.shared_nodes import get_id_property
    assert get_id_property("Party") == "party_id"
```

**2. API Endpoint Tests:**
```python
@pytest.mark.asyncio
async def test_returns_nodes_list(self, async_client, api_key_header, monkeypatch):
    monkeypatch.setattr("app.routes.shared_nodes.neo4j_client.execute_query", mock_func)
    response = await async_client.get("/api/ai/shared-nodes", headers=api_key_header)
    assert response.status_code == 200
```

**3. Repository Tests:**
```python
def test_inserts_event_record(self):
    repo = GraphEventsRepo()
    mock_conn = MagicMock()
    event_id = repo.log_event(conn=mock_conn, case_id="...", ...)
    mock_conn.execute.assert_called_once()
```

---

## Maintenance

- **Adding New Tests:** Add to appropriate test class in relevant file
- **Updating Fixtures:** Modify `conftest.py` shared fixtures
- **Schema Changes:** Update `SAMPLE_SCHEMA` in `conftest.py`
- **New Endpoints:** Add new test classes following existing patterns

Last Updated: December 31, 2025
