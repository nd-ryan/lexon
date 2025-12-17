import pytest
import uuid


class _FakeFlow:
    def __init__(self, schema_payload, result):
        self.state = type("State", (), {})()
        self.state.payload = None
        self.state.schema_payload = schema_payload
        self._result = result

    async def kickoff_async(self):
        return self._result


@pytest.mark.asyncio
async def test_kg_submit_deleted_shared_node_detached_not_deleted(
    async_client,
    user_id_header,
    monkeypatch,
):
    """
    When a shared (case_unique:false) node is removed from the case graph and the case is submitted to KG,
    the backend should detach it from the case (preserve the node), not DETACH DELETE it.
    """
    # Ensure bearer auth passes
    monkeypatch.setenv("FASTAPI_API_KEY", "test-api-key")

    case_id = str(uuid.uuid4())
    old_extracted = {
        "nodes": [
            {"label": "Case", "temp_id": "uuid-case", "properties": {"case_id": "c1", "name": "X"}},
            {"label": "Party", "temp_id": "uuid-party", "properties": {"party_id": "p1", "name": "P"}},
        ],
        "edges": [],
    }
    rec = {"id": case_id, "extracted": old_extracted, "kg_extracted": old_extracted, "kg_submitted_at": "2025-01-01T00:00:00Z"}

    # New graph deletes Party (shared node)
    new_nodes = [
        {"label": "Case", "temp_id": "uuid-case", "properties": {"case_id": "c1", "name": "X"}},
    ]
    flow_result = {"nodes": new_nodes, "edges": []}

    schema = [
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
        {"label": "Party", "case_unique": False, "can_create_new": True, "properties": {"party_id": {"type": "STRING"}}},
    ]

    monkeypatch.setattr("app.routes.kg.case_repo.get_case", lambda conn, _id: rec)
    monkeypatch.setattr("app.routes.kg.create_flow", lambda: _FakeFlow(schema, flow_result))

    # Avoid heavy uploader behavior beyond the deletion policy
    monkeypatch.setattr("app.lib.neo4j_uploader.Neo4jUploader.upload_graph_data", lambda self, nodes, edges: {"nodes": nodes, "edges": edges})
    monkeypatch.setattr("app.lib.property_filter.add_temp_ids", lambda uploaded: uploaded)
    monkeypatch.setattr("app.lib.property_filter.prepare_for_postgres_save", lambda data: data)
    monkeypatch.setattr("app.routes.kg.case_repo.update_case", lambda conn, _id, payload, user_id: True)
    monkeypatch.setattr("app.routes.kg.case_repo.set_kg_submitted", lambda conn, _id, user_id: True)
    monkeypatch.setattr("app.routes.kg.graph_events_repo.update_entity_ids_for_case", lambda **kwargs: 0)

    from app.lib.neo4j_client import neo4j_client
    executed = []

    def mock_execute(query, params=None):
        executed.append({"query": query, "params": params or {}})
        # detach_node_from_case query
        if "DELETE r" in query and "deleted_count" in query:
            return [{"deleted_count": 1}]
        return []

    neo4j_client.execute_query = mock_execute

    headers = {"Authorization": "Bearer test-api-key", **user_id_header}
    res = await async_client.post("/api/ai/kg/submit", json={"case_id": case_id}, headers=headers)
    assert res.status_code == 200
    assert res.json().get("success") is True

    # We should detach (DELETE r) and not DETACH DELETE the Party node.
    assert any("DELETE r" in q["query"] for q in executed)
    assert not any("DETACH DELETE" in q["query"] and ":`Party`" in q["query"] for q in executed)


@pytest.mark.asyncio
async def test_kg_submit_deleted_case_unique_isolated_deleted(
    async_client,
    user_id_header,
    monkeypatch,
):
    """
    When a case-unique node is removed from the case graph and the case is submitted to KG,
    it should be DETACH DELETE'd if isolated to the case.
    """
    monkeypatch.setenv("FASTAPI_API_KEY", "test-api-key")

    case_id = str(uuid.uuid4())
    old_extracted = {
        "nodes": [
            {"label": "Case", "temp_id": "uuid-case", "properties": {"case_id": "c2", "name": "Y"}},
            {"label": "Issue", "temp_id": "uuid-issue", "properties": {"issue_id": "i2", "label": "Issue"}},
        ],
        "edges": [],
    }
    rec = {"id": case_id, "extracted": old_extracted, "kg_extracted": old_extracted, "kg_submitted_at": "2025-01-01T00:00:00Z"}

    # New graph deletes Issue (case_unique)
    new_nodes = [
        {"label": "Case", "temp_id": "uuid-case", "properties": {"case_id": "c2", "name": "Y"}},
    ]
    flow_result = {"nodes": new_nodes, "edges": []}

    schema = [
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
        {"label": "Issue", "case_unique": True, "can_create_new": True, "properties": {"issue_id": {"type": "STRING"}}},
    ]

    monkeypatch.setattr("app.routes.kg.case_repo.get_case", lambda conn, _id: rec)
    monkeypatch.setattr("app.routes.kg.create_flow", lambda: _FakeFlow(schema, flow_result))
    monkeypatch.setattr("app.lib.neo4j_uploader.Neo4jUploader.upload_graph_data", lambda self, nodes, edges: {"nodes": nodes, "edges": edges})
    monkeypatch.setattr("app.lib.property_filter.add_temp_ids", lambda uploaded: uploaded)
    monkeypatch.setattr("app.lib.property_filter.prepare_for_postgres_save", lambda data: data)
    monkeypatch.setattr("app.routes.kg.case_repo.update_case", lambda conn, _id, payload, user_id: True)
    monkeypatch.setattr("app.routes.kg.case_repo.set_kg_submitted", lambda conn, _id, user_id: True)
    monkeypatch.setattr("app.routes.kg.graph_events_repo.update_entity_ids_for_case", lambda **kwargs: 0)

    from app.lib.neo4j_client import neo4j_client
    executed = []

    def mock_execute(query, params=None):
        executed.append({"query": query, "params": params or {}})
        # Isolation check sees no external connections => isolated
        if "RETURN connected, keys(connected) as props" in query:
            return []
        return []

    neo4j_client.execute_query = mock_execute

    headers = {"Authorization": "Bearer test-api-key", **user_id_header}
    res = await async_client.post("/api/ai/kg/submit", json={"case_id": case_id}, headers=headers)
    assert res.status_code == 200
    assert res.json().get("success") is True

    assert any("DETACH DELETE" in q["query"] and ":`Issue`" in q["query"] for q in executed)


