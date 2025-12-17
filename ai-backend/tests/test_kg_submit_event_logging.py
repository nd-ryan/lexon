import pytest


class _FakeFlow:
    def __init__(self, schema_payload, result):
        self.state = type("State", (), {})()
        self.state.payload = None
        self.state.schema_payload = schema_payload
        self._result = result

    async def kickoff_async(self):
        return self._result


@pytest.mark.asyncio
async def test_kg_submit_logs_delete_events_based_on_last_published_snapshot(
    async_client,
    user_id_header,
    monkeypatch,
):
    """
    On KG submit (non-first publish), graph_events should be emitted based on:
      old = cases.kg_extracted (last published)
      new = newly published payload (after Neo4j upload + ID assignment)

    In particular, if a node is removed from the published graph, we log a node delete event.
    """
    monkeypatch.setenv("FASTAPI_API_KEY", "test-api-key")

    case_id = "case-kg-submit-events-1"

    published = {
        "nodes": [
            {"label": "Case", "temp_id": "uuid-case", "properties": {"case_id": "c1", "name": "X"}},
            {"label": "Issue", "temp_id": "uuid-issue", "properties": {"issue_id": "i1", "label": "Issue"}},
        ],
        "edges": [],
    }

    # Draft can be anything; submit uses draft for flow input but diffs against kg_extracted for logging.
    rec = {
        "id": case_id,
        "extracted": published,
        "kg_extracted": published,
        "kg_submitted_at": "2025-01-01T00:00:00Z",
    }

    # New graph removes Issue
    flow_result = {
        "nodes": [
            {"label": "Case", "temp_id": "uuid-case", "properties": {"case_id": "c1", "name": "X"}},
        ],
        "edges": [],
    }

    schema = [
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
        {"label": "Issue", "case_unique": True, "can_create_new": True, "properties": {"issue_id": {"type": "STRING"}}},
    ]

    monkeypatch.setattr("app.routes.kg.case_repo.get_case", lambda conn, _id: rec)
    monkeypatch.setattr("app.routes.kg.create_flow", lambda: _FakeFlow(schema, flow_result))

    # Avoid heavy uploader behavior beyond allowing the route to complete.
    monkeypatch.setattr("app.lib.neo4j_uploader.Neo4jUploader.upload_graph_data", lambda self, nodes, edges: {"nodes": nodes, "edges": edges})
    monkeypatch.setattr("app.lib.property_filter.add_temp_ids", lambda uploaded: uploaded)
    monkeypatch.setattr("app.lib.property_filter.prepare_for_postgres_save", lambda data: data)
    monkeypatch.setattr("app.routes.kg.case_repo.update_case", lambda conn, _id, payload, user_id: True)
    monkeypatch.setattr("app.routes.kg.case_repo.set_kg_submitted", lambda conn, _id, user_id: True)
    monkeypatch.setattr("app.routes.kg.case_repo.set_kg_extracted", lambda conn, _id, payload: True)
    monkeypatch.setattr("app.routes.kg.graph_events_repo.update_entity_ids_for_case", lambda **kwargs: 0)

    logged = {"nodes": [], "edges": []}

    def log_node_event(**kwargs):
        logged["nodes"].append(kwargs)
        return "event-id"

    def log_edge_event(**kwargs):
        logged["edges"].append(kwargs)
        return "event-id"

    monkeypatch.setattr("app.routes.kg.graph_events_repo.log_node_event", log_node_event)
    monkeypatch.setattr("app.routes.kg.graph_events_repo.log_edge_event", log_edge_event)

    headers = {"Authorization": "Bearer test-api-key", **user_id_header}
    res = await async_client.post("/api/ai/kg/submit", json={"case_id": case_id}, headers=headers)
    assert res.status_code == 200
    assert res.json().get("success") is True

    # Should log a node delete event for Issue (uuid-issue)
    assert any(e.get("action") == "delete" and e.get("node_temp_id") == "uuid-issue" for e in logged["nodes"])


@pytest.mark.asyncio
async def test_kg_submit_does_not_log_node_create_for_is_existing(
    async_client,
    user_id_header,
    monkeypatch,
):
    """On first publish, node create events should skip is_existing nodes (edges still carry attribution)."""
    monkeypatch.setenv("FASTAPI_API_KEY", "test-api-key")

    case_id = "case-kg-submit-events-2"
    rec = {"id": case_id, "extracted": {"nodes": [], "edges": []}, "kg_extracted": None, "kg_submitted_at": None}

    flow_result = {
        "nodes": [
            {"label": "Case", "temp_id": "uuid-case", "properties": {"case_id": "c2", "name": "Y"}},
            {"label": "Doctrine", "temp_id": "uuid-doc", "is_existing": True, "properties": {"doctrine_id": "d1", "name": "Existing"}},
        ],
        "edges": [
            {"from": "uuid-case", "to": "uuid-doc", "label": "RELATES_TO_DOCTRINE", "properties": {}},
        ],
    }

    schema = [
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
        {"label": "Doctrine", "case_unique": False, "can_create_new": True, "properties": {"doctrine_id": {"type": "STRING"}}},
    ]

    monkeypatch.setattr("app.routes.kg.case_repo.get_case", lambda conn, _id: rec)
    monkeypatch.setattr("app.routes.kg.create_flow", lambda: _FakeFlow(schema, flow_result))
    monkeypatch.setattr("app.lib.neo4j_uploader.Neo4jUploader.upload_graph_data", lambda self, nodes, edges: {"nodes": nodes, "edges": edges})
    monkeypatch.setattr("app.lib.property_filter.add_temp_ids", lambda uploaded: uploaded)
    monkeypatch.setattr("app.lib.property_filter.prepare_for_postgres_save", lambda data: data)
    monkeypatch.setattr("app.routes.kg.case_repo.update_case", lambda conn, _id, payload, user_id: True)
    monkeypatch.setattr("app.routes.kg.case_repo.set_kg_submitted", lambda conn, _id, user_id: True)
    monkeypatch.setattr("app.routes.kg.case_repo.set_kg_extracted", lambda conn, _id, payload: True)
    monkeypatch.setattr("app.routes.kg.graph_events_repo.update_entity_ids_for_case", lambda **kwargs: 0)

    logged_nodes = []
    logged_edges = []

    monkeypatch.setattr("app.routes.kg.graph_events_repo.log_node_event", lambda **kw: logged_nodes.append(kw) or "event-id")
    monkeypatch.setattr("app.routes.kg.graph_events_repo.log_edge_event", lambda **kw: logged_edges.append(kw) or "event-id")

    headers = {"Authorization": "Bearer test-api-key", **user_id_header}
    res = await async_client.post("/api/ai/kg/submit", json={"case_id": case_id}, headers=headers)
    assert res.status_code == 200
    assert res.json().get("success") is True

    # Case node create is logged; Doctrine is_existing node create is skipped
    assert any(e.get("action") == "create" and e.get("node_temp_id") == "uuid-case" for e in logged_nodes)
    assert not any(e.get("action") == "create" and e.get("node_temp_id") == "uuid-doc" for e in logged_nodes)

    # Edge create should still be logged
    assert any(e.get("action") == "create" and e.get("edge_label") == "RELATES_TO_DOCTRINE" for e in logged_edges)


