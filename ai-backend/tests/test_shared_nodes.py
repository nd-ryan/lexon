"""Tests for the shared nodes API routes and helper functions."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import Request
from fastapi.testclient import TestClient


# ============================================================================
# Unit Tests for Helper Functions
# ============================================================================

class TestGetIdProperty:
    """Tests for get_id_property() helper function."""
    
    def test_simple_label(self):
        from app.routes.shared_nodes import get_id_property
        assert get_id_property("Party") == "party_id"
    
    def test_camelcase_label(self):
        from app.routes.shared_nodes import get_id_property
        assert get_id_property("ReliefType") == "relief_type_id"
    
    def test_multi_word_label(self):
        from app.routes.shared_nodes import get_id_property
        assert get_id_property("FactPattern") == "fact_pattern_id"
    
    def test_single_word_label(self):
        from app.routes.shared_nodes import get_id_property
        assert get_id_property("Case") == "case_id"
    
    def test_domain_label(self):
        from app.routes.shared_nodes import get_id_property
        assert get_id_property("Domain") == "domain_id"


class TestGetSharedLabels:
    """Tests for get_shared_labels() helper function."""
    
    def test_filters_case_unique_false(self, sample_schema):
        from app.routes.shared_nodes import get_shared_labels
        labels = get_shared_labels(sample_schema)
        
        assert "Domain" in labels
        assert "Party" in labels
        assert "Forum" in labels
        assert "Doctrine" in labels
    
    def test_excludes_case_unique_true(self, sample_schema):
        from app.routes.shared_nodes import get_shared_labels
        labels = get_shared_labels(sample_schema)
        
        assert "Case" not in labels
        assert "Proceeding" not in labels
    
    def test_empty_schema(self):
        from app.routes.shared_nodes import get_shared_labels
        labels = get_shared_labels([])
        assert labels == []
    
    def test_handles_non_dict_items(self):
        from app.routes.shared_nodes import get_shared_labels
        schema = [
            {"label": "Party", "case_unique": False},
            "not a dict",
            None,
            {"label": "Case", "case_unique": True},
        ]
        labels = get_shared_labels(schema)
        assert labels == ["Party"]


class TestGetMinPerCase:
    """Tests for get_min_per_case() helper function."""
    
    def test_returns_configured_value(self, sample_schema):
        from app.routes.shared_nodes import get_min_per_case
        assert get_min_per_case(sample_schema, "Domain") == 1
        assert get_min_per_case(sample_schema, "Party") == 1
    
    def test_returns_zero_when_not_set(self, sample_schema):
        from app.routes.shared_nodes import get_min_per_case
        # Doctrine doesn't have min_per_case set
        assert get_min_per_case(sample_schema, "Doctrine") == 0
    
    def test_returns_zero_for_unknown_label(self, sample_schema):
        from app.routes.shared_nodes import get_min_per_case
        assert get_min_per_case(sample_schema, "UnknownLabel") == 0


class TestGetNodeDisplayName:
    """Tests for get_node_display_name() helper function."""
    
    def test_uses_name_property(self):
        from app.routes.shared_nodes import get_node_display_name
        node = {"label": "Party", "properties": {"name": "John Smith"}}
        assert get_node_display_name(node) == "John Smith"
    
    def test_uses_label_property(self):
        from app.routes.shared_nodes import get_node_display_name
        node = {"label": "Doctrine", "properties": {"label": "Due Process"}}
        assert get_node_display_name(node) == "Due Process"
    
    def test_uses_type_property(self):
        from app.routes.shared_nodes import get_node_display_name
        node = {"label": "Category", "properties": {"type": "Civil Rights"}}
        assert get_node_display_name(node) == "Civil Rights"
    
    def test_truncates_long_names(self):
        from app.routes.shared_nodes import get_node_display_name
        long_name = "A" * 150
        node = {"label": "Party", "properties": {"name": long_name}}
        result = get_node_display_name(node)
        assert len(result) == 103  # 100 chars + "..."
        assert result.endswith("...")
    
    def test_fallback_to_label(self):
        from app.routes.shared_nodes import get_node_display_name
        node = {"label": "Party", "properties": {}}
        assert get_node_display_name(node) == "Party"
    
    def test_unknown_label_fallback(self):
        from app.routes.shared_nodes import get_node_display_name
        node = {"properties": {}}
        assert get_node_display_name(node) == "Unknown"


class TestGetUserId:
    """Tests for get_user_id() helper function."""
    
    def test_extracts_from_header(self):
        from app.routes.shared_nodes import get_user_id
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"X-User-Id": "user-abc-123"}
        
        assert get_user_id(mock_request) == "user-abc-123"
    
    def test_default_when_missing(self):
        from app.routes.shared_nodes import get_user_id
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}
        
        assert get_user_id(mock_request) == "admin"
    
    def test_default_when_empty(self):
        from app.routes.shared_nodes import get_user_id
        mock_request = MagicMock(spec=Request)
        # Make headers a dict-like object that returns None for missing keys
        mock_request.headers = {}
        
        # get() returns None for missing key, so should use default "admin"
        result = get_user_id(mock_request)
        assert result == "admin"


class TestFindCasesContainingNode:
    """Tests for find_cases_containing_node() helper function."""
    
    def test_extracts_case_name_from_extracted(self):
        from app.routes.shared_nodes import find_cases_containing_node
        
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            MagicMock(
                id="case-uuid-1",
                filename="test.pdf",
                kg_extracted=None,
                extracted={
                    "nodes": [
                        {"label": "Case", "properties": {"name": "Smith v. Jones", "citation": "123 F.3d"}},
                        {"label": "Party", "properties": {"party_id": "p1", "name": "Smith"}},
                    ]
                }
            )
        ])
        mock_db.execute = MagicMock(return_value=mock_result)
        
        cases = find_cases_containing_node(mock_db, "p1", "Party")
        
        assert len(cases) == 1
        assert cases[0]["case_name"] == "Smith v. Jones"
        assert cases[0]["citation"] == "123 F.3d"
    
    def test_fallback_to_filename(self):
        from app.routes.shared_nodes import find_cases_containing_node
        
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            MagicMock(
                id="case-uuid-1",
                filename="important_case.pdf",
                kg_extracted=None,
                extracted={
                    "nodes": [
                        {"label": "Party", "properties": {"party_id": "p1", "name": "Smith"}},
                    ]
                }
            )
        ])
        mock_db.execute = MagicMock(return_value=mock_result)
        
        cases = find_cases_containing_node(mock_db, "p1", "Party")
        
        assert len(cases) == 1
        assert cases[0]["case_name"] == "important_case.pdf"
    
    def test_counts_labels_correctly(self):
        from app.routes.shared_nodes import find_cases_containing_node
        
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            MagicMock(
                id="case-uuid-1",
                filename="test.pdf",
                kg_extracted=None,
                extracted={
                    "nodes": [
                        {"label": "Party", "properties": {"party_id": "p1"}},
                        {"label": "Party", "properties": {"party_id": "p2"}},
                        {"label": "Party", "properties": {"party_id": "p3"}},
                        {"label": "Case", "properties": {"case_id": "c1"}},
                    ]
                }
            )
        ])
        mock_db.execute = MagicMock(return_value=mock_result)
        
        cases = find_cases_containing_node(mock_db, "p1", "Party")
        
        assert cases[0]["labelCount"] == 3


class TestGetCaseNodeIds:
    """Tests for get_case_node_ids() helper function."""
    
    def test_extracts_all_ids(self):
        from app.routes.shared_nodes import get_case_node_ids
        
        nodes = [
            {"properties": {"party_id": "p1", "name": "Smith"}},
            {"properties": {"case_id": "c1", "citation": "123"}},
            {"properties": {"proceeding_id": "pr1"}},
        ]
        
        ids = get_case_node_ids(nodes)
        
        assert "p1" in ids
        assert "c1" in ids
        assert "pr1" in ids
        assert "Smith" not in ids
        assert "123" not in ids
    
    def test_handles_missing_properties(self):
        from app.routes.shared_nodes import get_case_node_ids
        
        nodes = [
            {"properties": {"party_id": "p1"}},
            {},  # No properties
            {"properties": {}},  # Empty properties
        ]
        
        ids = get_case_node_ids(nodes)
        assert ids == {"p1"}
    
    def test_handles_non_dict_nodes(self):
        from app.routes.shared_nodes import get_case_node_ids
        
        nodes = [
            {"properties": {"party_id": "p1"}},
            "not a dict",
            None,
        ]
        
        ids = get_case_node_ids(nodes)
        assert ids == {"p1"}


class TestRemoveNodeFromExtracted:
    """Tests for remove_node_from_extracted() helper function."""

    def test_removes_node_by_label_and_id_prop_and_incident_edges_by_temp_id(self):
        from app.routes.shared_nodes import remove_node_from_extracted

        extracted = {
            "nodes": [
                {"label": "Case", "temp_id": "n0", "properties": {"case_id": "c1"}},
                {"label": "Party", "temp_id": "n1", "properties": {"party_id": "p1", "name": "A"}},
                {"label": "Party", "temp_id": "n2", "properties": {"party_id": "p2", "name": "B"}},
            ],
            "edges": [
                {"from": "n0", "to": "n1", "label": "HAS_PARTY", "properties": {}},
                {"from": "n2", "to": "n0", "label": "HAS_PARTY", "properties": {}},
            ],
        }

        updated, removed_nodes, removed_edges = remove_node_from_extracted(extracted, "Party", "p1")
        assert removed_nodes == 1
        assert removed_edges == 1
        assert all(n.get("properties", {}).get("party_id") != "p1" for n in updated.get("nodes", []))
        assert all(e.get("to") != "n1" and e.get("from") != "n1" for e in updated.get("edges", []))

    def test_removes_catalog_reference_edges_by_node_id_when_node_absent(self):
        from app.routes.shared_nodes import remove_node_from_extracted

        # Catalog nodes (e.g. Domain) are stripped from extracted.nodes, but edges can reference their UUID directly.
        domain_id = "11111111-1111-1111-1111-111111111111"
        extracted = {
            "nodes": [
                {"label": "Case", "temp_id": "n0", "properties": {"case_id": "c1"}},
            ],
            "edges": [
                {"from": domain_id, "to": "n0", "label": "CONTAINS", "properties": {}},
            ],
        }

        updated, removed_nodes, removed_edges = remove_node_from_extracted(extracted, "Domain", domain_id)
        assert removed_nodes == 0
        assert removed_edges == 1
        assert updated["edges"] == []


# ============================================================================
# API Endpoint Tests
# ============================================================================

class TestListSharedNodesEndpoint:
    """Tests for GET /api/ai/shared-nodes endpoint."""
    
    @pytest.mark.asyncio
    async def test_requires_api_key(self, monkeypatch):
        """Should return 403 without API key."""
        from app import main
        from httpx import AsyncClient, ASGITransport
        
        # Skip DB table creation during tests
        monkeypatch.setattr(main, "ensure_all_tables", lambda engine: None)
        
        # Don't override API key dependency - test actual auth
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/ai/shared-nodes")
            assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_returns_nodes_list(self, async_client, api_key_header, monkeypatch, sample_schema):
        """Should return list of shared nodes."""
        # Mock schema loading
        monkeypatch.setattr(
            "app.routes.shared_nodes.load_schema",
            lambda: sample_schema
        )
        
        # Mock Neo4j response
        mock_results = [
            {"n": {"party_id": "p1", "name": "Test Party"}, "connectionCount": 5}
        ]
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: mock_results
        )
        
        response = await async_client.get(
            "/api/ai/shared-nodes?label=Party",
            headers=api_key_header
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "nodes" in data
        assert "labels" in data
    
    @pytest.mark.asyncio
    async def test_filters_by_label(self, async_client, api_key_header, monkeypatch, sample_schema):
        """Should filter nodes by label parameter."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        call_log = []
        def mock_execute(query, params=None):
            call_log.append(query)
            return []
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            mock_execute
        )
        
        await async_client.get(
            "/api/ai/shared-nodes?label=Party",
            headers=api_key_header
        )
        
        # Should only query Party nodes
        assert len(call_log) == 1
        assert "Party" in call_log[0]
    
    @pytest.mark.asyncio
    async def test_rejects_case_unique_label(self, async_client, api_key_header, monkeypatch, sample_schema):
        """Should reject labels that are case_unique=true."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        response = await async_client.get(
            "/api/ai/shared-nodes?label=Case",
            headers=api_key_header
        )
        
        assert response.status_code == 400


class TestGetSharedNodeEndpoint:
    """Tests for GET /api/ai/shared-nodes/{label}/{node_id} endpoint."""
    
    @pytest.mark.asyncio
    async def test_returns_node_details(self, async_client, api_key_header, monkeypatch, sample_schema):
        """Should return node with connected cases."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        # Mock Neo4j response
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: [{"n": {"party_id": "p1", "name": "Test"}, "connectionCount": 3}]
        )
        
        # Mock find_cases_containing_node
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: []
        )
        
        response = await async_client.get(
            "/api/ai/shared-nodes/Party/p1",
            headers=api_key_header
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "node" in data
        assert "connectedCases" in data
        assert "minPerCase" in data
    
    @pytest.mark.asyncio
    async def test_returns_404_for_missing_node(self, async_client, api_key_header, monkeypatch, sample_schema):
        """Should return 404 when node not found."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: []  # Empty result
        )
        
        response = await async_client.get(
            "/api/ai/shared-nodes/Party/nonexistent",
            headers=api_key_header
        )
        
        assert response.status_code == 404


class TestUpdateSharedNodeEndpoint:
    """Tests for PUT /api/ai/shared-nodes/{label}/{node_id} endpoint."""
    
    @pytest.mark.asyncio
    async def test_updates_node_properties(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Should update node properties in Neo4j."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        # Mock Neo4j - first call for get, second for update
        call_count = [0]
        def mock_execute(query, params=None):
            call_count[0] += 1
            return [{"n": {"party_id": "p1", "name": "Updated Name"}}]
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            mock_execute
        )
        
        # Mock find_cases_containing_node to return empty
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: []
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.put(
            "/api/ai/shared-nodes/Party/p1",
            headers=headers,
            json={"properties": {"name": "Updated Name"}}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    @pytest.mark.asyncio
    async def test_rejects_protected_properties(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Should reject updates to protected properties like *_id."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        # Mock Neo4j
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: [{"n": {"party_id": "p1", "name": "Test"}}]
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.put(
            "/api/ai/shared-nodes/Party/p1",
            headers=headers,
            json={"properties": {"party_id": "new-id"}}  # Only protected props
        )
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_logs_update_events(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Should log update events for connected cases."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: [{"n": {"party_id": "p1", "name": "Test"}}]
        )
        
        # Mock connected cases
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: [
                {"case_id": "case-1", "case_name": "Case 1", "labelCount": 2, "extracted": {}},
                {"case_id": "case-2", "case_name": "Case 2", "labelCount": 1, "extracted": {}},
            ]
        )
        
        # Track event logging
        logged_events = []
        def mock_log_event(conn, case_id, node_temp_id, node_label, action, user_id, properties=None, property_changes=None):
            logged_events.append({
                "case_id": case_id,
                "action": action,
                "user_id": user_id,
            })
            return "event-id"
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.graph_events_repo.log_node_event",
            mock_log_event
        )
        
        headers = {**api_key_header, **user_id_header}
        await async_client.put(
            "/api/ai/shared-nodes/Party/p1",
            headers=headers,
            json={"properties": {"name": "New Name"}}
        )
        
        # Should log one event per connected case
        assert len(logged_events) == 2
        assert all(e["action"] == "update" for e in logged_events)


class TestDeleteSharedNodeEndpoint:
    """Tests for DELETE /api/ai/shared-nodes/{label}/{node_id} endpoint."""
    
    @pytest.mark.asyncio
    async def test_deletes_node_fully(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Should delete node from KG when no min_per_case violations."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        # Mock Neo4j
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: [{"n": {"doctrine_id": "d1", "name": "Test"}, "deleted": 1}]
        )
        
        # Mock find_cases - empty means no min_per_case issues
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: []
        )
        
        # Mock event logging
        monkeypatch.setattr(
            "app.routes.shared_nodes.graph_events_repo.log_node_event",
            lambda **kwargs: "event-id"
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Doctrine/d1",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["partial"] is False
    
    @pytest.mark.asyncio
    async def test_returns_min_per_case_violation(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Should return error when deletion would violate min_per_case."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: [{"n": {"party_id": "p1", "name": "Test"}}]
        )
        
        # Mock case with only 1 Party (violates min_per_case=1 if deleted)
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: [
                {"case_id": "case-1", "case_name": "Case 1", "labelCount": 1, "extracted": {}},
            ]
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Party/p1",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "min_per_case_violation"
        assert "blockedCases" in data
    
    @pytest.mark.asyncio
    async def test_partial_delete_with_force(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Should perform partial delete when force_partial=true."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: [{"n": {"party_id": "p1"}, "deleted": 1}]
        )
        
        # One case can delete (2 parties), one cannot (1 party)
        updated_cases = []
        def mock_update_case(conn, case_id, payload, user_id):
            updated_cases.append({"case_id": case_id, "payload": payload, "user_id": user_id})
            return {"id": case_id}
        monkeypatch.setattr("app.routes.shared_nodes.case_repo.update_case", mock_update_case)

        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: [
                {
                    "case_id": "11111111-1111-1111-1111-111111111111",
                    "case_name": "Case 1",
                    "labelCount": 1,
                    "extracted": {
                        "nodes": [
                            {"label": "Party", "temp_id": "n1", "properties": {"party_id": "p1"}},
                        ],
                        "edges": [],
                    },
                },
                {
                    "case_id": "22222222-2222-2222-2222-222222222222",
                    "case_name": "Case 2",
                    "labelCount": 2,
                    "extracted": {
                        "nodes": [
                            {"label": "Case", "temp_id": "n0", "properties": {"case_id": "c1"}},
                            {"label": "Party", "temp_id": "n1", "properties": {"party_id": "p1"}},
                            {"label": "Party", "temp_id": "n2", "properties": {"party_id": "p2"}},
                        ],
                        "edges": [
                            {"from": "n0", "to": "n1", "label": "HAS_PARTY", "properties": {}},
                            {"from": "n2", "to": "n0", "label": "HAS_PARTY", "properties": {}},
                        ],
                    },
                },
            ]
        )
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.graph_events_repo.log_node_event",
            lambda **kwargs: "event-id"
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Party/p1?force_partial=true",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["partial"] is True
        assert "remainingCases" in data
        # Should persist extracted update only for the deletable case (Case 2)
        assert len(updated_cases) == 1
        assert updated_cases[0]["case_id"] == "22222222-2222-2222-2222-222222222222"
        updated_payload = updated_cases[0]["payload"]
        assert all(n.get("properties", {}).get("party_id") != "p1" for n in updated_payload.get("nodes", []))
        assert all(e.get("to") != "n1" and e.get("from") != "n1" for e in updated_payload.get("edges", []))
    
    @pytest.mark.asyncio
    async def test_logs_delete_events(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Should log delete events for affected cases."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: [{"n": {"doctrine_id": "d1"}, "deleted": 1}]
        )
        
        updated_cases = []
        monkeypatch.setattr(
            "app.routes.shared_nodes.case_repo.update_case",
            lambda conn, case_id, payload, user_id: updated_cases.append({"case_id": case_id, "payload": payload}) or {"id": case_id},
        )

        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: [
                {
                    "case_id": "33333333-3333-3333-3333-333333333333",
                    "case_name": "Case 1",
                    "labelCount": 2,
                    "extracted": {
                        "nodes": [
                            {"label": "Case", "temp_id": "n0", "properties": {"case_id": "c1"}},
                            {"label": "Doctrine", "temp_id": "n1", "properties": {"doctrine_id": "d1"}},
                        ],
                        "edges": [{"from": "n0", "to": "n1", "label": "HAS_DOCTRINE", "properties": {}}],
                    },
                },
            ]
        )
        
        logged_events = []
        def mock_log_event(**kwargs):
            logged_events.append(kwargs)
            return "event-id"
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.graph_events_repo.log_node_event",
            mock_log_event
        )
        
        headers = {**api_key_header, **user_id_header}
        await async_client.delete(
            "/api/ai/shared-nodes/Doctrine/d1",
            headers=headers
        )
        
        assert len(logged_events) == 1
        assert logged_events[0]["action"] == "delete"
        # Should also update Postgres extracted to remove the node reference
        assert len(updated_cases) == 1
        updated_payload = updated_cases[0]["payload"]
        assert all(n.get("properties", {}).get("doctrine_id") != "d1" for n in updated_payload.get("nodes", []))
    
    @pytest.mark.asyncio
    async def test_returns_404_for_missing_node(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Should return 404 when node not found."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        monkeypatch.setattr(
            "app.routes.shared_nodes.neo4j_client.execute_query",
            lambda q, p=None: []
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Party/nonexistent",
            headers=headers
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_catalog_node_detached_not_deleted_when_connected(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Catalog nodes (can_create_new=false) should be detached from cases but preserved in KG."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        # Track Neo4j queries to verify DETACH (not DELETE) is used
        neo4j_queries = []
        def mock_execute(query, params=None):
            neo4j_queries.append({"query": query, "params": params})
            # First call: check node exists
            if "RETURN n" in query:
                return [{"n": {"domain_id": "d1", "name": "Criminal Law"}}]
            # Second call: detach relationships
            elif "DELETE r" in query:
                return [{"deleted_count": 3}]
            return []
        
        monkeypatch.setattr("app.routes.shared_nodes.neo4j_client.execute_query", mock_execute)
        
        updated_cases = []
        monkeypatch.setattr(
            "app.routes.shared_nodes.case_repo.update_case",
            lambda conn, case_id, payload, user_id: updated_cases.append({"case_id": case_id, "payload": payload}) or {"id": case_id},
        )
        
        # Mock case with the domain node
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: [
                {
                    "case_id": "44444444-4444-4444-4444-444444444444",
                    "case_name": "Case 1",
                    "labelCount": 2,
                    "extracted": {
                        "nodes": [{"label": "Case", "temp_id": "n0", "properties": {"case_id": "c1"}}],
                        "edges": [{"from": "d1", "to": "n0", "label": "CONTAINS", "properties": {}}],
                    },
                },
            ]
        )
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.graph_events_repo.log_node_event",
            lambda **kwargs: "event-id"
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Domain/d1",  # Domain is catalog (can_create_new=false)
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["catalogNodePreserved"] is True
        assert "detached from all cases but preserved" in data["message"]
        
        # Verify no DETACH DELETE query was executed (only relationship deletion)
        delete_queries = [q for q in neo4j_queries if "DETACH DELETE" in q["query"]]
        assert len(delete_queries) == 0, "Catalog node should not be deleted from KG"
        
        # Verify relationship detachment was executed
        detach_queries = [q for q in neo4j_queries if "DELETE r" in q["query"]]
        assert len(detach_queries) == 1, "Should detach relationships"
        
        # Verify Postgres extracted was updated to remove catalog edge reference
        assert len(updated_cases) == 1
        assert updated_cases[0]["case_id"] == "44444444-4444-4444-4444-444444444444"
        assert updated_cases[0]["payload"]["edges"] == []
    
    @pytest.mark.asyncio
    async def test_orphaned_catalog_node_can_be_deleted(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Orphaned catalog nodes (no connections) can be fully deleted from KG."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        neo4j_queries = []
        def mock_execute(query, params=None):
            neo4j_queries.append({"query": query, "params": params})
            if "RETURN n" in query:
                return [{"n": {"forum_id": "f1", "name": "Orphaned Court"}}]
            elif "DETACH DELETE" in query:
                return [{"deleted": 1}]
            return []
        
        monkeypatch.setattr("app.routes.shared_nodes.neo4j_client.execute_query", mock_execute)
        
        # Mock empty cases (orphaned node)
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: []
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Forum/f1",  # Forum is catalog (can_create_new=false)
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data.get("catalogNodePreserved") is not True
        assert "deleted successfully" in data["message"]
        
        # Verify DETACH DELETE was executed for orphaned catalog node
        delete_queries = [q for q in neo4j_queries if "DETACH DELETE" in q["query"]]
        assert len(delete_queries) == 1, "Orphaned catalog node should be fully deleted"
    
    @pytest.mark.asyncio
    async def test_non_catalog_node_deleted_after_detachment(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Shared nodes referenced by cases should be detached from cases but preserved in KG (even if non-catalog)."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        neo4j_queries = []
        def mock_execute(query, params=None):
            neo4j_queries.append({"query": query, "params": params})
            if "RETURN n" in query:
                return [{"n": {"party_id": "p1", "name": "John Doe"}}]
            elif "DELETE r" in query:
                return [{"deleted_count": 2}]
            return []
        
        monkeypatch.setattr("app.routes.shared_nodes.neo4j_client.execute_query", mock_execute)

        updated_cases = []
        monkeypatch.setattr(
            "app.routes.shared_nodes.case_repo.update_case",
            lambda conn, case_id, payload, user_id: updated_cases.append({"case_id": case_id, "payload": payload}) or {"id": case_id},
        )
        
        # Mock cases (Party is non-catalog, can_create_new=true)
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: [
                {
                    "case_id": "55555555-5555-5555-5555-555555555555",
                    "case_name": "Case 1",
                    "labelCount": 2,
                    "extracted": {
                        "nodes": [
                            {"label": "Case", "temp_id": "n0", "properties": {"case_id": "c1"}},
                            {"label": "Party", "temp_id": "n1", "properties": {"party_id": "p1"}},
                            {"label": "Party", "temp_id": "n2", "properties": {"party_id": "p2"}},
                        ],
                        "edges": [{"from": "n0", "to": "n1", "label": "HAS_PARTY", "properties": {}}],
                    },
                },
            ]
        )
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.graph_events_repo.log_node_event",
            lambda **kwargs: "event-id"
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Party/p1",  # Party is non-catalog (can_create_new=true)
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data.get("catalogNodePreserved") is not True
        assert data.get("nodePreserved") is True
        assert "detached from all cases but preserved" in data["message"]
        
        # Verify no DETACH DELETE was executed (node preserved)
        delete_queries = [q for q in neo4j_queries if "DETACH DELETE" in q["query"]]
        assert len(delete_queries) == 0, "Node should be preserved when referenced by cases"

        # Verify relationship detachment was executed
        detach_queries = [q for q in neo4j_queries if "DELETE r" in q["query"]]
        assert len(detach_queries) == 1, "Should detach relationships"

        # Verify Postgres extracted was updated to remove Party(p1) from the case
        assert len(updated_cases) == 1
        updated_payload = updated_cases[0]["payload"]
        assert all(n.get("properties", {}).get("party_id") != "p1" for n in updated_payload.get("nodes", []))

    @pytest.mark.asyncio
    async def test_orphaned_non_catalog_node_can_be_deleted(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Orphaned non-catalog shared nodes (no case references) can be fully deleted from KG."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)

        neo4j_queries = []
        def mock_execute(query, params=None):
            neo4j_queries.append({"query": query, "params": params})
            if "RETURN n" in query:
                return [{"n": {"party_id": "p1", "name": "Orphaned Party"}}]
            elif "DETACH DELETE" in query:
                return [{"deleted": 1}]
            return []

        monkeypatch.setattr("app.routes.shared_nodes.neo4j_client.execute_query", mock_execute)

        # Mock empty cases (orphaned node)
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: []
        )

        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Party/p1",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data.get("nodePreserved") is not True
        assert "deleted successfully" in data["message"]

        # Verify DETACH DELETE was executed
        delete_queries = [q for q in neo4j_queries if "DETACH DELETE" in q["query"]]
        assert len(delete_queries) == 1, "Orphaned shared node should be fully deleted"
    
    @pytest.mark.asyncio
    async def test_min_per_case_error_prevents_any_deletion(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """When min_per_case validation fails, no deletion or detachment should occur."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        neo4j_queries = []
        def mock_execute(query, params=None):
            neo4j_queries.append({"query": query, "params": params})
            if "RETURN n" in query:
                return [{"n": {"party_id": "p1", "name": "Only Party"}}]
            return []
        
        monkeypatch.setattr("app.routes.shared_nodes.neo4j_client.execute_query", mock_execute)
        
        # Mock case with only 1 Party (violates min_per_case=1 if deleted)
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: [
                {"case_id": "case-1", "case_name": "Case 1", "labelCount": 1, "extracted": {}},
            ]
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Party/p1",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "min_per_case_violation"
        
        # Verify no deletion or detachment queries were executed
        delete_queries = [q for q in neo4j_queries if ("DELETE" in q["query"] and "RETURN n" not in q["query"])]
        assert len(delete_queries) == 0, "No deletion should occur when min_per_case is violated"
    
    @pytest.mark.asyncio
    async def test_detachment_removes_only_case_relationships(self, async_client, api_key_header, user_id_header, monkeypatch, sample_schema):
        """Detachment should only remove relationships to nodes in the specified case."""
        monkeypatch.setattr("app.routes.shared_nodes.load_schema", lambda: sample_schema)
        
        captured_case_node_ids = []
        def mock_execute(query, params=None):
            if "RETURN n" in query:
                return [{"n": {"domain_id": "d1", "name": "Criminal Law"}}]
            elif "DELETE r" in query:
                # Capture the case_node_ids parameter to verify filtering
                if params and "case_node_ids" in params:
                    captured_case_node_ids.extend(params["case_node_ids"])
                return [{"deleted_count": 2}]
            return []
        
        monkeypatch.setattr("app.routes.shared_nodes.neo4j_client.execute_query", mock_execute)
        
        # Mock case with specific node IDs
        monkeypatch.setattr(
            "app.routes.shared_nodes.find_cases_containing_node",
            lambda db, nid, label: [
                {
                    "case_id": "case-1",
                    "case_name": "Case 1",
                    "labelCount": 2,
                    "extracted": {
                        "nodes": [
                            {"properties": {"case_id": "c1"}},
                            {"properties": {"proceeding_id": "p1"}},
                            {"properties": {"issue_id": "i1"}},
                        ]
                    }
                },
            ]
        )
        
        monkeypatch.setattr(
            "app.routes.shared_nodes.graph_events_repo.log_node_event",
            lambda **kwargs: "event-id"
        )
        
        headers = {**api_key_header, **user_id_header}
        response = await async_client.delete(
            "/api/ai/shared-nodes/Domain/d1",
            headers=headers
        )
        
        assert response.status_code == 200
        # Verify that case_node_ids were correctly extracted and passed to query
        assert len(captured_case_node_ids) > 0, "Should pass case node IDs to detachment query"
        assert "c1" in captured_case_node_ids
        assert "p1" in captured_case_node_ids
        assert "i1" in captured_case_node_ids
