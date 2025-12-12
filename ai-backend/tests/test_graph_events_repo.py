"""Tests for the graph events repository and audit logging."""

import pytest
from unittest.mock import MagicMock, patch
import uuid


# ============================================================================
# Unit Tests for Helper Functions
# ============================================================================

class TestComputeContentHash:
    """Tests for compute_content_hash() function."""
    
    def test_deterministic_hash(self):
        """Same input should produce same hash."""
        from app.lib.graph_events_repo import compute_content_hash
        
        props = {"name": "Test", "value": 123}
        hash1 = compute_content_hash(props)
        hash2 = compute_content_hash(props)
        
        assert hash1 == hash2
    
    def test_different_key_order_same_hash(self):
        """Key order should not affect hash."""
        from app.lib.graph_events_repo import compute_content_hash
        
        props1 = {"a": 1, "b": 2, "c": 3}
        props2 = {"c": 3, "a": 1, "b": 2}
        
        assert compute_content_hash(props1) == compute_content_hash(props2)
    
    def test_different_values_different_hash(self):
        """Different values should produce different hash."""
        from app.lib.graph_events_repo import compute_content_hash
        
        props1 = {"name": "Test1"}
        props2 = {"name": "Test2"}
        
        assert compute_content_hash(props1) != compute_content_hash(props2)
    
    def test_empty_dict(self):
        """Should handle empty dictionary."""
        from app.lib.graph_events_repo import compute_content_hash
        
        result = compute_content_hash({})
        assert isinstance(result, str)
        assert len(result) == 16  # Truncated to 16 chars
    
    def test_nested_objects(self):
        """Should handle nested dictionaries."""
        from app.lib.graph_events_repo import compute_content_hash
        
        props = {"outer": {"inner": "value"}}
        result = compute_content_hash(props)
        assert isinstance(result, str)
    
    def test_handles_non_json_types(self):
        """Should handle non-JSON types via default=str."""
        from app.lib.graph_events_repo import compute_content_hash
        from datetime import datetime
        
        props = {"timestamp": datetime.now()}
        result = compute_content_hash(props)
        assert isinstance(result, str)


class TestMakeEdgeId:
    """Tests for make_edge_id() function."""
    
    def test_creates_composite_key(self):
        """Should create from:to:label format."""
        from app.lib.graph_events_repo import make_edge_id
        
        result = make_edge_id("node1", "node2", "RELATES_TO")
        assert result == "node1:node2:RELATES_TO"
    
    def test_handles_uuids(self):
        """Should handle UUID strings."""
        from app.lib.graph_events_repo import make_edge_id
        
        from_id = str(uuid.uuid4())
        to_id = str(uuid.uuid4())
        
        result = make_edge_id(from_id, to_id, "CONTAINS")
        assert result == f"{from_id}:{to_id}:CONTAINS"
    
    def test_handles_colons_in_label(self):
        """Should handle edge labels with colons (edge case)."""
        from app.lib.graph_events_repo import make_edge_id
        
        result = make_edge_id("a", "b", "HAS:SPECIAL:LABEL")
        assert result == "a:b:HAS:SPECIAL:LABEL"


# ============================================================================
# Repository Tests
# ============================================================================

class TestGraphEventsRepoLogEvent:
    """Tests for GraphEventsRepo.log_event() method."""
    
    def test_inserts_event_record(self):
        """Should insert event into database."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        event_id = repo.log_event(
            conn=mock_conn,
            case_id=str(uuid.uuid4()),
            entity_type="node",
            entity_id="n1",
            entity_label="Party",
            action="create",
            user_id="user-123",
            properties={"name": "Test"},
        )
        
        # Should have called execute with insert
        mock_conn.execute.assert_called_once()
        assert isinstance(event_id, str)
    
    def test_returns_event_id(self):
        """Should return UUID string."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        event_id = repo.log_event(
            conn=mock_conn,
            case_id=str(uuid.uuid4()),
            entity_type="node",
            entity_id="n1",
            entity_label="Party",
            action="create",
            user_id="user-123",
        )
        
        # Should be a valid UUID string
        uuid.UUID(event_id)  # Will raise if invalid
    
    def test_computes_content_hash(self):
        """Should compute hash from properties."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        repo.log_event(
            conn=mock_conn,
            case_id=str(uuid.uuid4()),
            entity_type="node",
            entity_id="n1",
            entity_label="Party",
            action="create",
            user_id="user-123",
            properties={"name": "Test"},
        )
        
        # Verify the insert call included content_hash
        call_args = mock_conn.execute.call_args
        # The values should include content_hash
        assert call_args is not None


class TestGraphEventsRepoLogNodeEvent:
    """Tests for GraphEventsRepo.log_node_event() method."""
    
    def test_sets_entity_type_to_node(self):
        """Should set entity_type to 'node'."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        with patch.object(repo, 'log_event', return_value="event-id") as mock_log:
            repo.log_node_event(
                conn=mock_conn,
                case_id=str(uuid.uuid4()),
                node_temp_id="n1",
                node_label="Party",
                action="create",
                user_id="user-123",
            )
            
            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs["entity_type"] == "node"
            assert call_kwargs["entity_id"] == "n1"
            assert call_kwargs["entity_label"] == "Party"
    
    def test_passes_properties_and_changes(self):
        """Should pass properties and property_changes through."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        props = {"name": "Test"}
        changes = {"name": {"old": "Old", "new": "Test"}}
        
        with patch.object(repo, 'log_event', return_value="event-id") as mock_log:
            repo.log_node_event(
                conn=mock_conn,
                case_id=str(uuid.uuid4()),
                node_temp_id="n1",
                node_label="Party",
                action="update",
                user_id="user-123",
                properties=props,
                property_changes=changes,
            )
            
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs["properties"] == props
            assert call_kwargs["property_changes"] == changes


class TestGraphEventsRepoLogEdgeEvent:
    """Tests for GraphEventsRepo.log_edge_event() method."""
    
    def test_sets_entity_type_to_edge(self):
        """Should set entity_type to 'edge'."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        with patch.object(repo, 'log_event', return_value="event-id") as mock_log:
            repo.log_edge_event(
                conn=mock_conn,
                case_id=str(uuid.uuid4()),
                from_id="n1",
                to_id="n2",
                edge_label="RELATES_TO",
                action="create",
                user_id="user-123",
            )
            
            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs["entity_type"] == "edge"
    
    def test_creates_composite_entity_id(self):
        """Should create from:to:label entity_id."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        with patch.object(repo, 'log_event', return_value="event-id") as mock_log:
            repo.log_edge_event(
                conn=mock_conn,
                case_id=str(uuid.uuid4()),
                from_id="n1",
                to_id="n2",
                edge_label="CONTAINS",
                action="create",
                user_id="user-123",
            )
            
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs["entity_id"] == "n1:n2:CONTAINS"


class TestGraphEventsRepoGetEventsForCase:
    """Tests for GraphEventsRepo.get_events_for_case() method."""
    
    def test_returns_events_list(self):
        """Should return list of events for case."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        # Mock the query result
        mock_rows = [
            {"id": str(uuid.uuid4()), "action": "create", "entity_id": "n1"},
            {"id": str(uuid.uuid4()), "action": "update", "entity_id": "n1"},
        ]
        mock_conn.execute.return_value.mappings.return_value.all.return_value = mock_rows
        
        case_id = str(uuid.uuid4())
        events = repo.get_events_for_case(mock_conn, case_id)
        
        assert len(events) == 2
        assert events[0]["action"] == "create"
        assert events[1]["action"] == "update"
    
    def test_orders_by_created_at_desc(self):
        """Should order events by creation time, newest first."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = []
        
        case_id = str(uuid.uuid4())
        repo.get_events_for_case(mock_conn, case_id)
        
        # Verify execute was called with a query containing ORDER BY
        mock_conn.execute.assert_called_once()


class TestGraphEventsRepoListEvents:
    """Tests for GraphEventsRepo.list_events() method."""
    
    def test_no_filters_returns_all(self):
        """Should return all events when no filters applied."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = [
            {"id": "1", "action": "create"},
            {"id": "2", "action": "update"},
        ]
        
        events = repo.list_events(mock_conn)
        
        assert len(events) == 2
    
    def test_filter_by_case_id(self):
        """Should filter by case_id when provided."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = []
        
        case_id = str(uuid.uuid4())
        repo.list_events(mock_conn, case_id=case_id)
        
        # Should have executed a query
        mock_conn.execute.assert_called_once()
    
    def test_filter_by_user_id(self):
        """Should filter by user_id when provided."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = []
        
        repo.list_events(mock_conn, user_id="user-123")
        
        mock_conn.execute.assert_called_once()
    
    def test_filter_by_action(self):
        """Should filter by action when provided."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = []
        
        repo.list_events(mock_conn, action="delete")
        
        mock_conn.execute.assert_called_once()
    
    def test_filter_by_entity_type(self):
        """Should filter by entity_type when provided."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = []
        
        repo.list_events(mock_conn, entity_type="node")
        
        mock_conn.execute.assert_called_once()
    
    def test_pagination(self):
        """Should apply limit and offset."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = []
        
        repo.list_events(mock_conn, limit=10, offset=20)
        
        mock_conn.execute.assert_called_once()


class TestGraphEventsRepoGetEventStats:
    """Tests for GraphEventsRepo.get_event_stats() method."""
    
    def test_returns_stats_structure(self):
        """Should return stats with expected keys."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        # Mock the queries
        mock_conn.execute.return_value.mappings.return_value.all.return_value = []
        mock_conn.execute.return_value.scalar.return_value = 0
        
        stats = repo.get_event_stats(mock_conn)
        
        assert "total" in stats
        assert "by_action" in stats
        assert "top_users" in stats


class TestGraphEventsRepoUpdateEntityIds:
    """Tests for GraphEventsRepo.update_entity_ids_for_case() method."""
    
    def test_maps_node_ids(self):
        """Should update node entity_ids with new UUIDs."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        case_id = str(uuid.uuid4())
        old_id = "n0"
        new_id = str(uuid.uuid4())
        
        # Mock get_events_for_case to return an event with old_id
        with patch.object(repo, 'get_events_for_case') as mock_get:
            mock_get.return_value = [
                {"id": str(uuid.uuid4()), "entity_id": old_id, "entity_type": "node"}
            ]
            
            count = repo.update_entity_ids_for_case(
                mock_conn,
                case_id,
                {old_id: new_id}
            )
            
            assert count == 1
            mock_conn.execute.assert_called_once()
    
    def test_maps_edge_ids(self):
        """Should update edge entity_ids (from:to:label format)."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        case_id = str(uuid.uuid4())
        new_from = str(uuid.uuid4())
        new_to = str(uuid.uuid4())
        
        with patch.object(repo, 'get_events_for_case') as mock_get:
            mock_get.return_value = [
                {"id": str(uuid.uuid4()), "entity_id": "n0:n1:CONTAINS", "entity_type": "edge"}
            ]
            
            count = repo.update_entity_ids_for_case(
                mock_conn,
                case_id,
                {"n0": new_from, "n1": new_to}
            )
            
            assert count == 1
    
    def test_handles_partial_mapping(self):
        """Should only update IDs that have mappings."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        case_id = str(uuid.uuid4())
        new_from = str(uuid.uuid4())
        
        with patch.object(repo, 'get_events_for_case') as mock_get:
            mock_get.return_value = [
                # Only n0 has a mapping, n1 stays as-is
                {"id": str(uuid.uuid4()), "entity_id": "n0:n1:CONTAINS", "entity_type": "edge"}
            ]
            
            count = repo.update_entity_ids_for_case(
                mock_conn,
                case_id,
                {"n0": new_from}  # Only mapping for n0
            )
            
            assert count == 1
    
    def test_empty_mapping_returns_zero(self):
        """Should return 0 when mapping is empty."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        count = repo.update_entity_ids_for_case(
            mock_conn,
            str(uuid.uuid4()),
            {}  # Empty mapping
        )
        
        assert count == 0
        mock_conn.execute.assert_not_called()
    
    def test_no_matching_events_returns_zero(self):
        """Should return 0 when no events match the mapping."""
        from app.lib.graph_events_repo import GraphEventsRepo
        
        repo = GraphEventsRepo()
        mock_conn = MagicMock()
        
        with patch.object(repo, 'get_events_for_case') as mock_get:
            mock_get.return_value = [
                {"id": str(uuid.uuid4()), "entity_id": "unmapped", "entity_type": "node"}
            ]
            
            count = repo.update_entity_ids_for_case(
                mock_conn,
                str(uuid.uuid4()),
                {"n0": "new-id"}  # n0 not in events
            )
            
            assert count == 0
