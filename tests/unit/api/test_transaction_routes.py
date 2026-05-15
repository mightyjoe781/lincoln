import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_transactions_returns_200_empty(client: AsyncClient):
    resp = await client.get("/api/v1/transactions")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_get_transaction_nonexistent_returns_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/transactions/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_transaction_without_auth_returns_401(unauthed_client: AsyncClient):
    resp = await unauthed_client.patch(
        f"/api/v1/transactions/{uuid.uuid4()}",
        json={"description": "Updated"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_transaction_without_auth_returns_401(unauthed_client: AsyncClient):
    resp = await unauthed_client.delete(f"/api/v1/transactions/{uuid.uuid4()}")
    assert resp.status_code == 401
