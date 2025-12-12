import os

import pytest


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        pytest.skip(f"Missing required env var(s) for Neo4j integration test: {', '.join(missing)}")


@pytest.mark.integration
def test_neo4j_client_execute_query_return_1():
    _require_env("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")

    # Import inside the test so we can skip cleanly before module import side-effects.
    from app.lib.neo4j_client import neo4j_client

    results = neo4j_client.execute_query("RETURN 1 as test")
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["test"] == 1


@pytest.mark.integration
def test_neo4j_client_can_count_nodes_and_relationships():
    _require_env("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")

    from app.lib.neo4j_client import neo4j_client

    nodes = neo4j_client.execute_query("MATCH (n) RETURN count(n) as count")
    assert isinstance(nodes, list)
    assert len(nodes) == 1
    assert isinstance(nodes[0]["count"], int)
    assert nodes[0]["count"] >= 0

    rels = neo4j_client.execute_query("MATCH ()-[r]->() RETURN count(r) as count")
    assert isinstance(rels, list)
    assert len(rels) == 1
    assert isinstance(rels[0]["count"], int)
    assert rels[0]["count"] >= 0


