import uuid
from datetime import date
import pytest
from app.db.models.document import Document
from app.db.models.invoice import Invoice
from app.services.invoice_service import InvoiceService


async def _seed(db):
    doc = Document(
        filename="seed.pdf", original_name="seed.pdf", file_type="pdf_invoice",
        mime_type="application/pdf", file_size=100, file_path="/tmp/seed.pdf",
        checksum=f"seed_{uuid.uuid4().hex}", status="done",
    )
    db.add(doc)
    await db.flush()
    invoices = [
        Invoice(document_id=doc.id, vendor_name="Acme Corp", invoice_date=date(2024, 1, 15), total_amount=1000, currency="USD"),
        Invoice(document_id=doc.id, vendor_name="Acme Ltd", invoice_date=date(2024, 3, 10), total_amount=2000, currency="USD"),
        Invoice(document_id=doc.id, vendor_name="Beta Inc", invoice_date=date(2024, 7, 1), total_amount=500, currency="EUR"),
        Invoice(document_id=doc.id, vendor_name="Gamma Co", invoice_date=date(2024, 2, 20), total_amount=750, currency="USD"),
        Invoice(document_id=doc.id, vendor_name="Acme Global", invoice_date=date(2024, 5, 25), total_amount=1500, currency="USD"),
    ]
    for inv in invoices:
        db.add(inv)
    await db.commit()


@pytest.mark.asyncio
async def test_list_filter_by_vendor(db):
    await _seed(db)
    results = await InvoiceService(db).list(vendor_name="Acme")
    assert all("Acme" in r.vendor_name for r in results)


@pytest.mark.asyncio
async def test_list_date_range(db):
    await _seed(db)
    results = await InvoiceService(db).list(date_from=date(2024, 1, 1), date_to=date(2024, 6, 30))
    assert all(date(2024, 1, 1) <= r.invoice_date <= date(2024, 6, 30) for r in results)


@pytest.mark.asyncio
async def test_list_pagination(db):
    await _seed(db)
    page1 = await InvoiceService(db).list(page=1, page_size=2)
    page2 = await InvoiceService(db).list(page=2, page_size=2)
    assert len(page1) == 2
    assert page1[0].id != page2[0].id
