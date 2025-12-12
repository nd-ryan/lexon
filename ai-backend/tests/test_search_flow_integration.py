import os

import pytest


def _env_truthy(name: str) -> bool:
    v = os.getenv(name)
    if v is None:
        return False
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        pytest.skip(f"Missing required env var(s) for integration test: {', '.join(missing)}")


@pytest.mark.integration
def test_search_flow_doctrines_query_end_to_end():
    """
    Extremely heavyweight integration test.

    Runs the full SearchFlow:
    - uses an LLM (e.g. OpenAI) for query generation + synthesis
    - uses Neo4j MCP tools for Cypher execution (spawns `mcp-neo4j-cypher`)

    Opt-in only via RUN_SEARCH_FLOW_INTEGRATION=1.
    """
    if not _env_truthy("RUN_SEARCH_FLOW_INTEGRATION"):
        pytest.skip("Set RUN_SEARCH_FLOW_INTEGRATION=1 to run this test")

    _require_env("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "OPENAI_API_KEY")

    from app.flow_search import SearchFlow
    from app.models.search import StructuredSearchResponse

    flow = SearchFlow()
    flow.state.query = "Can you get all the doctrines from the database"

    result = flow.kickoff()
    assert isinstance(result, StructuredSearchResponse)
    assert result.query == flow.state.query
    assert isinstance(result.cypher_queries, list)
    assert isinstance(result.raw_results, list)
    assert isinstance(result.explanation, str)
    assert result.explanation.strip() != ""


