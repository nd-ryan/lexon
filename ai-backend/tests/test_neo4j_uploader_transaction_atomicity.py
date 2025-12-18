import pytest
from contextlib import contextmanager


class _FakeTx:
    pass


class _FakeNeo4jClient:
    def __init__(self, fail_on_edge: bool):
        self.fail_on_edge = fail_on_edge
        self.committed = False
        self.rolled_back = False
        self.executed = []  # (query, params)

    @contextmanager
    def transaction(self):
        tx = _FakeTx()
        try:
            yield tx
        except Exception:
            self.rolled_back = True
            raise
        else:
            self.committed = True

    def execute_query_in_tx(self, tx, query: str, parameters=None):
        self.executed.append((query, parameters or {}))
        if self.fail_on_edge and "MERGE_EDGE" in query:
            raise RuntimeError("simulated edge write failure")
        # Simulate the uploader's expectation that node queries return [{"id": ...}]
        if "RETURN" in query:
            return [{"id": "00000000-0000-0000-0000-000000000000"}]
        return []


def test_uploader_rolls_back_when_any_edge_write_fails(sample_schema):
    """If an edge write fails, the uploader must not commit partial node writes."""
    from app.lib.neo4j_uploader import Neo4jUploader

    neo4j_client = _FakeNeo4jClient(fail_on_edge=True)
    uploader = Neo4jUploader(schema_payload=sample_schema, neo4j_client=neo4j_client)

    # Minimal original data structures
    original_nodes = [{"label": "Case", "properties": {"case_id": "c1"}}]
    original_edges = [{"from": "n1", "to": "n2", "label": "RELATES_TO_POLICY"}]

    node_queries = [("CREATE (n:`Case`) SET n.case_id = randomUUID() RETURN n.case_id as id", {}, 0, "Case", "case_id")]
    edge_queries = [("MERGE_EDGE", {"from_uuid": "a", "to_uuid": "b"})]

    with pytest.raises(RuntimeError, match="edge write failure"):
        uploader._execute_in_transaction(node_queries, edge_queries, original_nodes, original_edges)

    assert neo4j_client.rolled_back is True
    assert neo4j_client.committed is False


def test_uploader_commits_when_all_writes_succeed(sample_schema):
    from app.lib.neo4j_uploader import Neo4jUploader

    neo4j_client = _FakeNeo4jClient(fail_on_edge=False)
    uploader = Neo4jUploader(schema_payload=sample_schema, neo4j_client=neo4j_client)

    original_nodes = [{"label": "Case", "properties": {"case_id": "c1"}}]
    original_edges = [{"from": "n1", "to": "n2", "label": "RELATES_TO_POLICY"}]

    node_queries = [("CREATE (n:`Case`) SET n.case_id = randomUUID() RETURN n.case_id as id", {}, 0, "Case", "case_id")]
    edge_queries = [("MERGE_EDGE", {"from_uuid": "a", "to_uuid": "b"})]

    uploader._execute_in_transaction(node_queries, edge_queries, original_nodes, original_edges)

    assert neo4j_client.committed is True
    assert neo4j_client.rolled_back is False


