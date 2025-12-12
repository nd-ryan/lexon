import os

import pytest
from neo4j import GraphDatabase, READ_ACCESS, WRITE_ACCESS


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        pytest.skip(f"Missing required env var(s) for Neo4j integration test: {', '.join(missing)}")


@pytest.mark.integration
def test_direct_driver_can_run_simple_query():
    _require_env("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")

    uri = os.environ["NEO4J_URI"]
    username = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.getenv("NEO4J_DATABASE")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            record = session.run("RETURN 1 as test").single()
            assert record is not None
            assert record["test"] == 1
    finally:
        driver.close()


@pytest.mark.integration
def test_direct_driver_read_and_write_sessions_work():
    _require_env("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")

    uri = os.environ["NEO4J_URI"]
    username = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.getenv("NEO4J_DATABASE")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
            record = session.run("RETURN 1 as num").single()
            assert record is not None
            assert record["num"] == 1

        with driver.session(database=database, default_access_mode=WRITE_ACCESS) as session:
            record = session.run("RETURN 1 as num").single()
            assert record is not None
            assert record["num"] == 1
    finally:
        driver.close()


@pytest.mark.integration
def test_direct_driver_can_count_nodes():
    _require_env("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")

    uri = os.environ["NEO4J_URI"]
    username = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.getenv("NEO4J_DATABASE")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
            record = session.run("MATCH (n) RETURN count(n) as count LIMIT 1").single()
            assert record is not None
            assert isinstance(record["count"], int)
            assert record["count"] >= 0
    finally:
        driver.close()


