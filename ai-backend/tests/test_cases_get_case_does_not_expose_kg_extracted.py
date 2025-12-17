import pytest


@pytest.mark.asyncio
async def test_get_case_does_not_expose_kg_extracted(
    async_client,
    api_key_header,
    monkeypatch,
):
    case_id = "case-1"
    case_data = {
        "id": case_id,
        "filename": "test.pdf",
        "status": "success",
        "extracted": {"nodes": [], "edges": []},
        "kg_extracted": {"nodes": [{"label": "Case", "temp_id": "uuid", "properties": {"case_id": "c1"}}], "edges": []},
        "kg_submitted_at": None,
        "updated_at": None,
    }

    monkeypatch.setattr("app.routes.cases.case_repo.get_case", lambda conn, _id: case_data)

    res = await async_client.get(f"/api/ai/cases/{case_id}", headers=api_key_header)
    assert res.status_code == 200
    payload = res.json()
    assert payload.get("success") is True
    assert "case" in payload
    assert "kg_extracted" not in payload["case"]


