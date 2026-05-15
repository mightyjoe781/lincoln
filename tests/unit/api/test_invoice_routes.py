import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient

from app.db.models.document import Document
from app.db.models.invoice import Invoice


def _make_document(**kwargs) -> Document:
    defaults = dict(
        filename="invoice.pdf",
        original_name="invoice.pdf",
        file_type="pdf_invoice",
        mime_type="application/pdf",
        file_size=1024,
        file_path="/tmp/invoice.pdf",
        checksum=uuid.uuid4().hex,
        status="done",
    )
    defaults.update(kwargs)
    return Document(**defaults)


def _make_invoice(document_id: uuid.UUID, **kwargs) -> Invoice:
    now = datetime.now(timezone.utc)
    defaults = dict(
        document_id=document_id,
        vendor_name="Acme Corp",
        invoice_date=date(2024, 1, 15),
        invoice_number="INV-001",
        total_amount="199.99",
        currency="USD",
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


@pytest.mark.asyncio
async def test_list_invoices_returns_200_empty(client: AsyncClient):
    resp = await client.get("/api/v1/invoices")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_list_invoices_with_vendor_name_filter(client: AsyncClient, db):
    doc = _make_document()
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    inv = _make_invoice(doc.id, vendor_name="FilterVendor")
    db.add(inv)
    await db.commit()

    resp = await client.get("/api/v1/invoices", params={"vendor_name": "FilterVendor"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all("FilterVendor" in (i["vendor_name"] or "") for i in body["items"])


@pytest.mark.asyncio
async def test_list_invoices_with_date_filters(client: AsyncClient, db):
    doc = _make_document()
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    inv = _make_invoice(doc.id, invoice_date=date(2024, 6, 1))
    db.add(inv)
    await db.commit()

    resp = await client.get(
        "/api/v1/invoices",
        params={"date_from": "2024-01-01", "date_to": "2024-12-31"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body


@pytest.mark.asyncio
async def test_get_invoice_nonexistent_returns_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/invoices/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_invoice_without_auth_returns_401(unauthed_client: AsyncClient):
    resp = await unauthed_client.patch(
        f"/api/v1/invoices/{uuid.uuid4()}",
        json={"vendor_name": "New Vendor"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_invoice_nonexistent_returns_404(client: AsyncClient):
    resp = await client.patch(
        f"/api/v1/invoices/{uuid.uuid4()}",
        json={"vendor_name": "New Vendor"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_invoice_without_auth_returns_401(unauthed_client: AsyncClient):
    resp = await unauthed_client.delete(f"/api/v1/invoices/{uuid.uuid4()}")
    assert resp.status_code == 401
