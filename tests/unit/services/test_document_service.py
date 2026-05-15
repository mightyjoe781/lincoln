import uuid
import pytest
from app.services.document_service import DocumentService


class MockStorage:
    async def save(self, data, filename, checksum):
        return f"/tmp/{checksum}.pdf"

    async def delete(self, path):
        pass

    async def exists(self, path):
        return True


@pytest.mark.asyncio
async def test_upload_returns_pending_status(db, mock_celery_task):
    # After Celery refactor: upload returns immediately with status=pending
    svc = DocumentService(db, MockStorage())
    csv_bytes = b"date,description,amount\n2024-01-01,Test,100.00\n"
    doc = await svc.upload(csv_bytes, "statement.csv", "text/csv")
    assert doc.status == "pending"


@pytest.mark.asyncio
async def test_upload_enqueues_parse_task(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    csv_bytes = b"date,description,amount\n2024-01-01,Test,100.00\n"
    doc = await svc.upload(csv_bytes, "statement.csv", "text/csv")
    mock_celery_task.delay.assert_called_once_with(str(doc.id))


@pytest.mark.asyncio
async def test_upload_duplicate_returns_existing_document(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    csv_bytes = b"date,description,amount\n2024-01-01,Dup,50.00\n"
    doc1 = await svc.upload(csv_bytes, "a.csv", "text/csv")
    doc2 = await svc.upload(csv_bytes, "b.csv", "text/csv")
    assert doc1.id == doc2.id
    # Task is only enqueued once — duplicate skips re-processing
    mock_celery_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_upload_stores_file_metadata(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    csv_bytes = b"date,description,amount\n2024-01-01,Meta,200.00\n"
    doc = await svc.upload(csv_bytes, "meta.csv", "text/csv")
    assert doc.original_name == "meta.csv"
    assert doc.mime_type == "text/csv"
    assert doc.file_type == "csv_statement"
    assert doc.file_size == len(csv_bytes)
    assert doc.checksum  # SHA-256 is set
