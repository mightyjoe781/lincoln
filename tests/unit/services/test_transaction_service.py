import uuid
from datetime import date
import pytest
from app.db.models.document import Document
from app.db.models.transaction import Transaction
from app.services.transaction_service import TransactionService


async def _seed(db):
    doc = Document(
        filename="bank.csv", original_name="bank.csv", file_type="csv_statement",
        mime_type="text/csv", file_size=200, file_path="/tmp/bank.csv",
        checksum=f"txn_{uuid.uuid4().hex}", status="done",
    )
    db.add(doc)
    await db.flush()
    for t in [
        Transaction(document_id=doc.id, transaction_date=date(2024, 1, 5), description="Salary", amount=5000, currency="USD"),
        Transaction(document_id=doc.id, transaction_date=date(2024, 1, 10), description="Rent", amount=-1500, currency="USD"),
        Transaction(document_id=doc.id, transaction_date=date(2024, 2, 1), description="Groceries", amount=-87.5, currency="USD"),
    ]:
        db.add(t)
    await db.commit()


@pytest.mark.asyncio
async def test_list_date_range(db):
    await _seed(db)
    results = await TransactionService(db).list(date_from=date(2024, 1, 1), date_to=date(2024, 1, 31))
    assert all(date(2024, 1, 1) <= r.transaction_date <= date(2024, 1, 31) for r in results)
