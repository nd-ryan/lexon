"""Shared test fixtures for the backend test suite."""

import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport
from typing import Any, Dict, List


# Sample schema for testing (subset of schema_v3.json)
SAMPLE_SCHEMA = [
    {
        "label": "Domain",
        "case_unique": False,
        "can_create_new": False,
        "min_per_case": 1,
        "properties": {
            "domain_id": {"type": "STRING"},
            "name": {"type": "STRING"},
        },
    },
    {
        "label": "Party",
        "case_unique": False,
        "can_create_new": True,
        "min_per_case": 1,
        "properties": {
            "party_id": {"type": "STRING"},
            "name": {"type": "STRING"},
            "party_type": {"type": "STRING"},
        },
    },
    {
        "label": "Forum",
        "case_unique": False,
        "can_create_new": False,
        "min_per_case": 1,
        "properties": {
            "forum_id": {"type": "STRING"},
            "name": {"type": "STRING"},
        },
    },
    {
        "label": "Case",
        "case_unique": True,
        "can_create_new": True,
        "min_per_case": 1,
        "properties": {
            "case_id": {"type": "STRING"},
            "name": {"type": "STRING"},
            "citation": {"type": "STRING"},
        },
    },
    {
        "label": "Proceeding",
        "case_unique": True,
        "can_create_new": True,
        "min_per_case": 1,
        "properties": {
            "proceeding_id": {"type": "STRING"},
            "stage": {"type": "STRING"},
        },
    },
    {
        "label": "Doctrine",
        "case_unique": False,
        "can_create_new": True,
        "properties": {
            "doctrine_id": {"type": "STRING"},
            "name": {"type": "STRING"},
        },
    },
]


@pytest.fixture
def sample_schema() -> List[Dict[str, Any]]:
    """Provide sample schema data for tests."""
    return SAMPLE_SCHEMA.copy()


@pytest.fixture
def mock_neo4j_client(monkeypatch):
    """Mock the Neo4j client's execute_query method."""
    mock_results = []
    
    def mock_execute_query(query: str, params: Dict = None):
        return mock_results
    
    mock = MagicMock()
    mock.execute_query = mock_execute_query
    mock.set_results = lambda results: mock_results.clear() or mock_results.extend(results)
    
    monkeypatch.setattr(
        "app.lib.neo4j_client.neo4j_client.execute_query",
        mock_execute_query
    )
    
    return mock


@pytest.fixture
def mock_db_connection():
    """Create a mock database connection for testing."""
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=MagicMock(
        mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    return mock_conn


@pytest.fixture
def mock_db_session(mock_db_connection):
    """Create a mock SQLAlchemy session."""
    mock_session = MagicMock()
    mock_session.execute = MagicMock(return_value=MagicMock(
        mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    mock_session.connection = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=mock_db_connection),
        __exit__=MagicMock(return_value=None)
    ))
    return mock_session


@pytest.fixture
async def async_client(monkeypatch, mock_db_session):
    """Create an async test client for the FastAPI app."""
    from app import main
    from app.lib.security import get_api_key
    from app.lib.db import get_db
    
    # Skip DB table creation during tests (if function exists)
    if hasattr(main, "ensure_all_tables"):
        monkeypatch.setattr(main, "ensure_all_tables", lambda engine: None)
    
    # Mock Neo4j client to avoid real connection attempts
    mock_neo4j = MagicMock()
    mock_neo4j.execute_query = MagicMock(return_value=[])
    monkeypatch.setattr("app.lib.neo4j_client.neo4j_client", mock_neo4j)
    monkeypatch.setattr("app.routes.shared_nodes.neo4j_client", mock_neo4j)
    # Also mock neo4j_client in concept_linking analysis service
    monkeypatch.setattr("app.lib.concept_linking.analysis_service.neo4j_client", mock_neo4j)
    
    # Override API key dependency to bypass authentication in tests
    async def mock_get_api_key():
        return "test-api-key"
    
    # Override DB dependency to use mock
    def mock_get_db_dependency():
        yield mock_db_session
    
    main.app.dependency_overrides[get_api_key] = mock_get_api_key
    main.app.dependency_overrides[get_db] = mock_get_db_dependency
    
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    
    # Clean up overrides
    main.app.dependency_overrides.clear()


@pytest.fixture
def api_key_header():
    """Provide the API key header for authenticated requests."""
    import os
    api_key = os.environ.get("FASTAPI_API_KEY", "test-api-key")
    return {"X-API-Key": api_key}


@pytest.fixture
def user_id_header():
    """Provide a user ID header for requests."""
    return {"X-User-Id": "test-user-123"}


@pytest.fixture
def sample_node_data():
    """Provide sample node data for testing."""
    return {
        "party_id": "abc-123-def",
        "name": "Test Party",
        "party_type": "individual",
    }


@pytest.fixture
def sample_case_data():
    """Provide sample case data for testing."""
    return {
        "id": "case-uuid-123",
        "filename": "test_case.pdf",
        "extracted": {
            "nodes": [
                {
                    "label": "Case",
                    "temp_id": "n0",
                    "properties": {
                        "case_id": "case-001",
                        "name": "Smith v. Jones",
                        "citation": "123 F.3d 456",
                    },
                },
                {
                    "label": "Party",
                    "temp_id": "n1",
                    "properties": {
                        "party_id": "party-001",
                        "name": "John Smith",
                    },
                },
            ],
            "edges": [],
        },
    }
