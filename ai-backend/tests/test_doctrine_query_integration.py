import os

import pytest


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        pytest.skip(f"Missing required env var(s) for Neo4j integration test: {', '.join(missing)}")


@pytest.mark.integration
def test_can_query_doctrines_shape():
    """
    Integration test: verifies the Doctrine label can be queried and returns expected keys.

    This intentionally does NOT assert doctrines exist (some DBs may have 0),
    only that the query runs and has consistent output shape when it returns rows.
    """
    _require_env("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")

    from app.lib.neo4j_client import neo4j_client

    cypher = """
    MATCH (d:Doctrine)
    RETURN d.name as doctrine_name,
           d.description as description,
           d.category as category,
           d.source as source,
           id(d) as doctrine_id,
           labels(d) as labels,
           properties(d) as all_properties
    ORDER BY d.name
    LIMIT 50
    """

    results = neo4j_client.execute_query(cypher)
    assert isinstance(results, list)

    for row in results:
        assert "doctrine_name" in row
        assert "doctrine_id" in row
        assert "labels" in row
        assert "all_properties" in row


