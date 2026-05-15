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


@pytest.mark.asyncio
async def test_get_document_returns_none_for_missing(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    result = await svc.get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_existing_document(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    csv_bytes = b"date,description,amount\n2024-01-01,Test,100.00\n"
    created = await svc.upload(csv_bytes, "test.csv", "text/csv")
    fetched = await svc.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_list_documents_returns_all(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    for i in range(3):
        await svc.upload(
            f"date,description,amount\n2024-01-01,T{i},{i * 100}\n".encode(),
            f"f{i}.csv",
            "text/csv",
        )
    docs = await svc.list(page=1, page_size=10)
    assert len(docs) >= 3


@pytest.mark.asyncio
async def test_list_pagination_second_page(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    for i in range(5):
        await svc.upload(
            f"date,description,amount\n2024-01-{i + 1:02d},T,{i}\n".encode(),
            f"p{i}.csv",
            "text/csv",
        )
    page1 = await svc.list(page=1, page_size=2)
    page2 = await svc.list(page=2, page_size=2)
    ids_p1 = {d.id for d in page1}
    ids_p2 = {d.id for d in page2}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_delete_document_returns_true(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    csv_bytes = b"date,description,amount\n2024-01-01,Del,1.00\n"
    doc = await svc.upload(csv_bytes, "del.csv", "text/csv")
    result = await svc.delete(doc.id)
    assert result is True
    assert await svc.get(doc.id) is None


@pytest.mark.asyncio
async def test_delete_missing_document_returns_false(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    assert await svc.delete(uuid.uuid4()) is False
