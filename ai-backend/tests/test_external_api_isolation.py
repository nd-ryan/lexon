"""
Tests for external API route isolation.

These tests verify that:
1. External API key cannot access internal routes
2. Internal API key (FASTAPI_API_KEY) cannot access external routes
3. Edge secret is required for external routes (when configured)
4. Health and version endpoints work without auth
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def isolation_client(monkeypatch):
    """
    Create a test client with BOTH internal and external auth configured.
    
    This fixture does NOT override auth dependencies, allowing us to test
    the actual auth behavior.
    """
    # Set up test API keys
    monkeypatch.setenv("FASTAPI_API_KEY", "internal-test-key-12345")
    monkeypatch.setenv("LEXON_API_KEYS", "external-test-key-abcde,external-test-key-fghij")
    monkeypatch.setenv("LEXON_EDGE_SECRET", "edge-secret-xyz")
    
    # Import after setting env vars so they're picked up
    # Need to reload modules to pick up new env vars
    import importlib
    import app.lib.security
    import app.lib.external_auth
    importlib.reload(app.lib.security)
    importlib.reload(app.lib.external_auth)
    
    from app import main
    
    # Skip DB table creation during tests
    monkeypatch.setattr(main, "ensure_all_tables", lambda engine: None)
    
    # Mock Neo4j client
    mock_neo4j = MagicMock()
    mock_neo4j.execute_query = MagicMock(return_value=[])
    monkeypatch.setattr("app.lib.neo4j_client.neo4j_client", mock_neo4j)
    
    # Mock DB session
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=MagicMock(
        mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    ))
    
    from app.lib.db import get_db
    def mock_get_db():
        yield mock_db
    main.app.dependency_overrides[get_db] = mock_get_db
    
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    
    main.app.dependency_overrides.clear()


class TestExternalCannotAccessInternal:
    """Test that external API keys cannot access internal routes."""
    
    @pytest.mark.asyncio
    async def test_external_key_rejected_on_internal_route(self, isolation_client):
        """External API key should be rejected on /api/ai/* routes."""
        response = await isolation_client.get(
            "/api/ai/shared-nodes",
            headers={
                "X-API-Key": "external-test-key-abcde",
                "X-Lexon-Edge": "edge-secret-xyz",
            }
        )
        # Internal routes use FASTAPI_API_KEY, so external key should fail
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_external_key_rejected_on_internal_v1_route(self, isolation_client):
        """External API key should be rejected on /api/v1/* routes."""
        response = await isolation_client.post(
            "/api/v1/chat",
            headers={
                "X-API-Key": "external-test-key-abcde",
                "X-Lexon-Edge": "edge-secret-xyz",
            },
            json={"input": "test"}
        )
        # Internal routes use FASTAPI_API_KEY, so external key should fail
        assert response.status_code == 401


class TestInternalCannotAccessExternal:
    """Test that internal API key cannot access external routes."""
    
    @pytest.mark.asyncio
    async def test_internal_key_rejected_on_external_route(self, isolation_client):
        """Internal FASTAPI_API_KEY should be rejected on /external/v1/* routes."""
        response = await isolation_client.post(
            "/external/v1/query",
            headers={
                "X-API-Key": "internal-test-key-12345",
                "X-Lexon-Edge": "edge-secret-xyz",
            },
            json={"query": "test query"}
        )
        # External routes use LEXON_API_KEYS, so internal key should fail
        assert response.status_code == 401


class TestEdgeSecretRequired:
    """Test that edge secret is required for external routes."""
    
    @pytest.mark.asyncio
    async def test_missing_edge_secret_rejected(self, isolation_client):
        """Request without X-Lexon-Edge header should be rejected."""
        response = await isolation_client.post(
            "/external/v1/query",
            headers={
                "X-API-Key": "external-test-key-abcde",
                # No X-Lexon-Edge header
            },
            json={"query": "test query"}
        )
        assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_wrong_edge_secret_rejected(self, isolation_client):
        """Request with wrong X-Lexon-Edge value should be rejected."""
        response = await isolation_client.post(
            "/external/v1/query",
            headers={
                "X-API-Key": "external-test-key-abcde",
                "X-Lexon-Edge": "wrong-secret",
            },
            json={"query": "test query"}
        )
        assert response.status_code == 403


class TestHealthAndVersionNoAuth:
    """Test that health and version endpoints work without auth."""
    
    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, isolation_client):
        """Health endpoint should work without any auth headers."""
        response = await isolation_client.get("/external/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
    
    @pytest.mark.asyncio
    async def test_version_no_auth_required(self, isolation_client):
        """Version endpoint should work without any auth headers."""
        response = await isolation_client.get("/external/v1/version")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert data["api"] == "Lexon External API"


class TestOpenAPISpecRequiresAuth:
    """Test that OpenAPI spec endpoint requires authentication."""
    
    @pytest.mark.asyncio
    async def test_openapi_without_auth_rejected(self, isolation_client):
        """OpenAPI spec endpoint should require auth."""
        response = await isolation_client.get("/external/v1/openapi.json")
        # Without edge secret or API key, should fail
        assert response.status_code in (401, 403)
    
    @pytest.mark.asyncio
    async def test_openapi_with_wrong_key_rejected(self, isolation_client):
        """OpenAPI spec should reject wrong API key."""
        response = await isolation_client.get(
            "/external/v1/openapi.json",
            headers={
                "X-API-Key": "wrong-key",
                "X-Lexon-Edge": "edge-secret-xyz",
            }
        )
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_openapi_with_valid_auth_returns_spec(self, isolation_client):
        """OpenAPI spec should return valid JSON with proper auth."""
        response = await isolation_client.get(
            "/external/v1/openapi.json",
            headers={
                "X-API-Key": "external-test-key-abcde",
                "X-Lexon-Edge": "edge-secret-xyz",
            }
        )
        assert response.status_code == 200
        data = response.json()
        # Verify it's a valid OpenAPI spec
        assert "openapi" in data or "paths" in data
        assert "info" in data
        # Verify only external routes are present
        paths = data.get("paths", {})
        for path in paths.keys():
            assert not path.startswith("/api/"), f"Internal route found in external OpenAPI: {path}"


class TestMultiKeyRotation:
    """Test that multiple API keys work for rotation support."""
    
    @pytest.mark.asyncio
    async def test_first_key_works(self, isolation_client, monkeypatch):
        """First key in LEXON_API_KEYS should be accepted."""
        # Mock run_query_flow to avoid actual execution
        async def mock_run_query_flow(query):
            return {"enriched_nodes": []}
        
        with patch("app.routes.external.query.run_query_flow", mock_run_query_flow):
            response = await isolation_client.post(
                "/external/v1/query",
                headers={
                    "X-API-Key": "external-test-key-abcde",
                    "X-Lexon-Edge": "edge-secret-xyz",
                },
                json={"query": "test query"}
            )
        # Should succeed (not 401)
        assert response.status_code != 401
    
    @pytest.mark.asyncio
    async def test_second_key_works(self, isolation_client, monkeypatch):
        """Second key in LEXON_API_KEYS should also be accepted."""
        async def mock_run_query_flow(query):
            return {"enriched_nodes": []}
        
        with patch("app.routes.external.query.run_query_flow", mock_run_query_flow):
            response = await isolation_client.post(
                "/external/v1/query",
                headers={
                    "X-API-Key": "external-test-key-fghij",  # Second key
                    "X-Lexon-Edge": "edge-secret-xyz",
                },
                json={"query": "test query"}
            )
        # Should succeed (not 401)
        assert response.status_code != 401


class TestRequestValidation:
    """Test request validation for external API."""
    
    @pytest.mark.asyncio
    async def test_extra_fields_rejected(self, isolation_client):
        """Unknown fields in request body should be rejected."""
        response = await isolation_client.post(
            "/external/v1/query",
            headers={
                "X-API-Key": "external-test-key-abcde",
                "X-Lexon-Edge": "edge-secret-xyz",
            },
            json={
                "query": "test query",
                "unknown_field": "should be rejected"
            }
        )
        assert response.status_code == 422  # Validation error
    
    @pytest.mark.asyncio
    async def test_query_too_long_rejected(self, isolation_client):
        """Query exceeding max_length should be rejected."""
        response = await isolation_client.post(
            "/external/v1/query",
            headers={
                "X-API-Key": "external-test-key-abcde",
                "X-Lexon-Edge": "edge-secret-xyz",
            },
            json={
                "query": "x" * 2001  # Exceeds 2000 char limit
            }
        )
        assert response.status_code == 422  # Validation error
    
    @pytest.mark.asyncio
    async def test_empty_query_rejected(self, isolation_client):
        """Empty query should be rejected."""
        response = await isolation_client.post(
            "/external/v1/query",
            headers={
                "X-API-Key": "external-test-key-abcde",
                "X-Lexon-Edge": "edge-secret-xyz",
            },
            json={
                "query": ""
            }
        )
        assert response.status_code == 422  # Validation error


class TestQueryLogging:
    """Test that query content is never logged."""
    
    @pytest.mark.asyncio
    async def test_query_content_not_in_logs(self, isolation_client, monkeypatch, caplog):
        """Query content should never appear in logs."""
        import logging
        caplog.set_level(logging.INFO)
        
        sensitive_query = "SENSITIVE_SECRET_DATA_12345"
        
        async def mock_run_query_flow(query):
            return {"enriched_nodes": []}
        
        with patch("app.routes.external.query.run_query_flow", mock_run_query_flow):
            response = await isolation_client.post(
                "/external/v1/query",
                headers={
                    "X-API-Key": "external-test-key-abcde",
                    "X-Lexon-Edge": "edge-secret-xyz",
                },
                json={"query": sensitive_query}
            )
        
        # Check that sensitive content is not in any log records
        for record in caplog.records:
            assert sensitive_query not in record.message, \
                f"Sensitive query content found in log: {record.message}"
