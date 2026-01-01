import pytest


@pytest.mark.asyncio
async def test_delete_case_not_kg_submitted_no_neo4j_calls(
    async_client,
    api_key_header,
    user_id_header,
    monkeypatch,
):
    """If a case was never submitted to KG, deleting it should not touch Neo4j."""
    case_id = "case-draft-1"
    case_data = {
        "id": case_id,
        "filename": "draft.pdf",
        "file_key": None,
        "kg_submitted_at": None,
        "extracted": {"nodes": [], "edges": []},
    }

    monkeypatch.setattr("app.routes.cases.case_repo.get_case", lambda conn, _id: case_data)
    monkeypatch.setattr("app.routes.cases.case_repo.delete_case", lambda conn, _id: True)

    # Draft-only cases should not emit graph_events delete logs (no KG mutation ever occurred)
    def should_not_log(*args, **kwargs):
        raise AssertionError("graph_events should not be written for draft-only case deletion")

    monkeypatch.setattr("app.routes.cases.graph_events_repo.log_node_event", should_not_log)
    monkeypatch.setattr("app.routes.cases.graph_events_repo.log_edge_event", should_not_log)

    from app.lib.neo4j_client import neo4j_client

    def should_not_call(*args, **kwargs):
        raise AssertionError("Neo4j should not be touched when kg_submitted_at is null")

    neo4j_client.execute_query = should_not_call

    headers = {**api_key_header, **user_id_header}
    res = await async_client.delete(f"/api/ai/cases/{case_id}", headers=headers)
    assert res.status_code == 200
    assert res.json().get("success") is True


@pytest.mark.asyncio
async def test_delete_case_detaches_is_existing_and_shared_nodes(
    async_client,
    api_key_header,
    user_id_header,
    monkeypatch,
):
    """When deleting a KG-submitted case, is_existing and non-case-unique nodes should be detached (preserved)."""
    case_id = "case-kg-1"
    case_data = {
        "id": case_id,
        "filename": "submitted.pdf",
        "file_key": None,
        "kg_submitted_at": "2025-01-01T00:00:00Z",
        "extracted": {
            "nodes": [
                {"label": "Case", "temp_id": "uuid-case", "properties": {"case_id": "c-kg-1", "name": "X"}},
                # is_existing shared node
                {"label": "Party", "temp_id": "uuid-party", "is_existing": True, "properties": {"party_id": "p-ex", "name": "Existing"}},
                # non-case-unique node created by this case
                {"label": "Doctrine", "temp_id": "uuid-doc", "properties": {"doctrine_id": "d-new", "name": "New"}},
            ],
            "edges": [],
        },
    }

    # Schema: Party + Doctrine are shared (case_unique false); Case is case-unique.
    sample_schema = [
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
        {"label": "Party", "case_unique": False, "can_create_new": True, "properties": {"party_id": {"type": "STRING"}}},
        {"label": "Doctrine", "case_unique": False, "can_create_new": True, "properties": {"doctrine_id": {"type": "STRING"}}},
    ]

    monkeypatch.setattr("app.routes.cases.case_repo.get_case", lambda conn, _id: case_data)
    monkeypatch.setattr("app.routes.cases.case_repo.delete_case", lambda conn, _id: True)
    monkeypatch.setattr("app.routes.kg.load_schema", lambda: sample_schema)
    monkeypatch.setattr("app.routes.cases.graph_events_repo.log_node_event", lambda **kwargs: "event-id")
    monkeypatch.setattr("app.routes.cases.graph_events_repo.log_edge_event", lambda **kwargs: "event-id")

    from app.lib.neo4j_client import neo4j_client
    executed = []

    def mock_execute(query, params=None):
        executed.append({"query": query, "params": params or {}})
        if "DELETE r" in query and "deleted_count" in query:
            return [{"deleted_count": 1}]
        return []

    neo4j_client.execute_query = mock_execute

    headers = {**api_key_header, **user_id_header}
    res = await async_client.delete(f"/api/ai/cases/{case_id}", headers=headers)
    assert res.status_code == 200
    assert res.json().get("success") is True

    # We should have detached relationships for Party and Doctrine (DELETE r queries).
    detach_queries = [q for q in executed if "DELETE r" in q["query"]]
    assert len(detach_queries) >= 2

    # No global deletes for Party/Doctrine in this pathway (Case itself may be deleted).
    delete_party = [q for q in executed if "DETACH DELETE" in q["query"] and ":`Party`" in q["query"]]
    delete_doctrine = [q for q in executed if "DETACH DELETE" in q["query"] and ":`Doctrine`" in q["query"]]
    assert len(delete_party) == 0
    assert len(delete_doctrine) == 0

    # Isolation checks may run for case-unique nodes like Case; ensure we didn't run isolation checks for shared nodes.
    isolation_queries = [q for q in executed if "RETURN connected, labels(connected) as labels, keys(connected) as props" in q["query"]]
    assert all((q["params"] or {}).get("node_id") == "c-kg-1" for q in isolation_queries)


@pytest.mark.asyncio
async def test_delete_case_returns_404_when_missing(
    async_client,
    api_key_header,
    user_id_header,
    monkeypatch,
):
    monkeypatch.setattr("app.routes.cases.case_repo.get_case", lambda conn, _id: None)
    headers = {**api_key_header, **user_id_header}
    res = await async_client.delete("/api/ai/cases/missing-case", headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_case_case_unique_external_connections_detach_only(
    async_client,
    api_key_header,
    user_id_header,
    monkeypatch,
):
    """
    Defensive safety: when deleting a case, case-unique nodes should only be deleted from Neo4j
    if they are isolated to the case. If they have external connections, detach only.
    """
    # Case contains one case-unique node (Issue) and the Case node itself.
    case_id = "case-1"
    case_data = {
        "id": case_id,
        "filename": "test.pdf",
        "file_key": None,
        "kg_submitted_at": "2025-01-01T00:00:00Z",
        "extracted": {
            "nodes": [
                {"label": "Case", "temp_id": "n0", "properties": {"case_id": "c1", "name": "X"}},
                {"label": "Issue", "temp_id": "n1", "properties": {"issue_id": "i1", "label": "Issue"}},
            ],
            "edges": [],
        },
    }

    monkeypatch.setattr("app.routes.cases.case_repo.get_case", lambda conn, _id: case_data)
    monkeypatch.setattr("app.routes.cases.case_repo.delete_case", lambda conn, _id: True)

    # Minimal schema: Issue is case-unique; Case is case-unique too, but we only care about Issue here.
    sample_schema = [
        {"label": "Issue", "case_unique": True, "can_create_new": True, "properties": {"issue_id": {"type": "STRING"}}},
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
    ]
    monkeypatch.setattr("app.routes.kg.load_schema", lambda: sample_schema)

    # Stub event logging to avoid DB writes during test.
    monkeypatch.setattr("app.routes.cases.graph_events_repo.log_node_event", lambda **kwargs: "event-id")
    monkeypatch.setattr("app.routes.cases.graph_events_repo.log_edge_event", lambda **kwargs: "event-id")

    # Control Neo4j behavior by mocking execute_query on the globally-patched client.
    from app.lib.neo4j_client import neo4j_client

    executed = []

    def mock_execute(query, params=None):
        executed.append({"query": query, "params": params or {}})

        # check_node_isolation query (returns connected + props)
        if "RETURN connected, labels(connected) as labels, keys(connected) as props" in query:
            # External connection: connected node is case-unique and NOT in case_node_ids
            return [{"connected": {"case_id": "c-external"}, "labels": ["Case"], "props": ["case_id"]}]

        # detach_node_from_case query
        if "DELETE r" in query and "deleted_count" in query:
            return [{"deleted_count": 2}]

        # delete_node query (DETACH DELETE) should not run for Issue in this scenario
        return []

    neo4j_client.execute_query = mock_execute

    headers = {**api_key_header, **user_id_header}
    res = await async_client.delete(f"/api/ai/cases/{case_id}", headers=headers)
    assert res.status_code == 200
    assert res.json().get("success") is True

    # Ensure we detached relationships (DELETE r) and did not DETACH DELETE the Issue node.
    detach_queries = [q for q in executed if "DELETE r" in q["query"]]
    assert len(detach_queries) >= 1

    delete_queries = [q for q in executed if "DETACH DELETE" in q["query"] and ":`Issue`" in q["query"]]
    assert len(delete_queries) == 0


@pytest.mark.asyncio
async def test_delete_case_case_unique_isolated_deleted(
    async_client,
    api_key_header,
    user_id_header,
    monkeypatch,
):
    """If a case-unique node is isolated to the case, it should be deleted from Neo4j on case deletion."""
    case_id = "case-2"
    case_data = {
        "id": case_id,
        "filename": "test.pdf",
        "file_key": None,
        "kg_submitted_at": "2025-01-01T00:00:00Z",
        "extracted": {
            "nodes": [
                {"label": "Case", "temp_id": "n0", "properties": {"case_id": "c2", "name": "Y"}},
                {"label": "Issue", "temp_id": "n1", "properties": {"issue_id": "i2", "label": "Issue"}},
            ],
            "edges": [],
        },
    }

    monkeypatch.setattr("app.routes.cases.case_repo.get_case", lambda conn, _id: case_data)
    monkeypatch.setattr("app.routes.cases.case_repo.delete_case", lambda conn, _id: True)

    sample_schema = [
        {"label": "Issue", "case_unique": True, "can_create_new": True, "properties": {"issue_id": {"type": "STRING"}}},
        {"label": "Case", "case_unique": True, "can_create_new": True, "properties": {"case_id": {"type": "STRING"}}},
    ]
    monkeypatch.setattr("app.routes.kg.load_schema", lambda: sample_schema)

    monkeypatch.setattr("app.routes.cases.graph_events_repo.log_node_event", lambda **kwargs: "event-id")
    monkeypatch.setattr("app.routes.cases.graph_events_repo.log_edge_event", lambda **kwargs: "event-id")

    from app.lib.neo4j_client import neo4j_client
    executed = []

    def mock_execute(query, params=None):
        executed.append({"query": query, "params": params or {}})

        # Isolation check sees no external connections (returns empty set) => isolated
        if "RETURN connected, labels(connected) as labels, keys(connected) as props" in query:
            return []

        return []

    neo4j_client.execute_query = mock_execute

    headers = {**api_key_header, **user_id_header}
    res = await async_client.delete(f"/api/ai/cases/{case_id}", headers=headers)
    assert res.status_code == 200
    assert res.json().get("success") is True

    # Ensure DETACH DELETE was invoked for Issue in this scenario.
    delete_queries = [q for q in executed if "DETACH DELETE" in q["query"] and ":`Issue`" in q["query"]]
    assert len(delete_queries) == 1


