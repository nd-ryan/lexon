import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client(monkeypatch):
    from app import main

    # Skip DB table creation during tests
    monkeypatch.setattr(main, "ensure_all_tables", lambda engine: None)

    transport = ASGITransport(app=main.app, lifespan="on")
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
