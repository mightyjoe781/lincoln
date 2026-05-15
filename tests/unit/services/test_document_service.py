import pytest
from app.services.document_service import DocumentService
from app.storage.local import LocalFileStorage


class MockStorage:
    async def save(self, data, filename, checksum):
        return f"/tmp/{checksum}.pdf"

    async def delete(self, path):
        pass

    async def exists(self, path):
        return True


@pytest.mark.asyncio
async def test_upload_sets_status_done_on_success(db, tmp_path):
    storage = MockStorage()
    svc = DocumentService(db, storage)
    csv_bytes = b"date,description,amount\n2024-01-01,Test,100.00\n"
    doc = await svc.upload(csv_bytes, "statement.csv", "text/csv")
    assert doc.status == "done"


@pytest.mark.asyncio
async def test_upload_sets_status_failed_on_parse_error(db):
    storage = MockStorage()
    svc = DocumentService(db, storage)
    doc = await svc.upload(b"not a pdf", "bad.pdf", "application/pdf")
    assert doc.status == "failed"
    assert doc.error_message is not None


@pytest.mark.asyncio
async def test_upload_duplicate_returns_existing_document(db):
    storage = MockStorage()
    svc = DocumentService(db, storage)
    csv_bytes = b"date,description,amount\n2024-01-01,Dup,50.00\n"
    doc1 = await svc.upload(csv_bytes, "a.csv", "text/csv")
    doc2 = await svc.upload(csv_bytes, "b.csv", "text/csv")
    assert doc1.id == doc2.id
