import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.db.models.document import Document


def _make_document(**kwargs) -> Document:
    defaults = dict(
        filename="test.csv",
        original_name="test.csv",
        file_type="csv_statement",
        mime_type="text/csv",
        file_size=100,
        file_path="/tmp/test.csv",
        checksum=uuid.uuid4().hex,
        status="pending",
    )
    defaults.update(kwargs)
    return Document(**defaults)


@pytest.mark.asyncio
async def test_list_documents_returns_200_with_pagination(client: AsyncClient):
    resp = await client.get("/api/v1/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body


@pytest.mark.asyncio
async def test_get_document_existing_returns_200(client: AsyncClient, db):
    doc = _make_document()
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    resp = await client.get(f"/api/v1/documents/{doc.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(doc.id)


@pytest.mark.asyncio
async def test_get_document_nonexistent_returns_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_without_auth_returns_401(unauthed_client: AsyncClient):
    resp = await unauthed_client.delete(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_document_nonexistent_returns_404(client: AsyncClient):
    resp = await client.delete(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_without_auth_returns_401(unauthed_client: AsyncClient):
    resp = await unauthed_client.post(
        "/api/v1/documents/upload",
        files=[("files", ("test.csv", b"date,description,amount\n", "text/csv"))],
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_wrong_mime_type_returns_422(client: AsyncClient):
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("test.txt", b"hello world", "text/plain"))],
    )
    assert resp.status_code == 422
    assert "unsupported type" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_oversized_file_returns_413(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size_bytes", 10)

    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("big.csv", b"date,description,amount\n" * 100, "text/csv"))],
    )
    assert resp.status_code == 413
