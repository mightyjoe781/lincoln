import uuid
from datetime import date

import pytest

from app.db.models.document import Document
from app.db.models.transaction import Transaction
from app.services.transaction_service import TransactionService


async def _seed(db):
    doc = Document(
        filename="bank.csv",
        original_name="bank.csv",
        file_type="csv_statement",
        mime_type="text/csv",
        file_size=200,
        file_path="/tmp/bank.csv",
        checksum=f"txn_{uuid.uuid4().hex}",
        status="done",
    )
    db.add(doc)
    await db.flush()
    for t in [
        Transaction(
            document_id=doc.id,
            transaction_date=date(2024, 1, 5),
            description="Salary",
            amount=5000,
            currency="USD",
        ),
        Transaction(
            document_id=doc.id,
            transaction_date=date(2024, 1, 10),
            description="Rent",
            amount=-1500,
            currency="USD",
        ),
        Transaction(
            document_id=doc.id,
            transaction_date=date(2024, 2, 1),
            description="Groceries",
            amount=-87.5,
            currency="USD",
        ),
    ]:
        db.add(t)
    await db.commit()


@pytest.mark.asyncio
async def test_list_date_range(db):
    await _seed(db)
    results = await TransactionService(db).list(
        date_from=date(2024, 1, 1), date_to=date(2024, 1, 31)
    )
    assert all(date(2024, 1, 1) <= r.transaction_date <= date(2024, 1, 31) for r in results)


@pytest.mark.asyncio
async def test_list_amount_range_filter(db):
    await _seed(db)
    results = await TransactionService(db).list(amount_min=-2000, amount_max=0)
    assert all(-2000 <= float(r.amount) <= 0 for r in results if r.amount is not None)


@pytest.mark.asyncio
async def test_list_currency_filter(db):
    await _seed(db)
    results = await TransactionService(db).list(currency="USD")
    assert all(r.currency == "USD" for r in results)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_list_sort_by_amount_asc(db):
    await _seed(db)
    results = await TransactionService(db).list(sort_by="amount", sort_order="asc")
    amounts = [float(r.amount) for r in results if r.amount is not None]
    assert amounts == sorted(amounts)


@pytest.mark.asyncio
async def test_get_transaction_returns_none_for_missing(db):
    result = await TransactionService(db).get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_transaction_by_id(db):
    await _seed(db)
    all_txns = await TransactionService(db).list()
    target = all_txns[0]
    fetched = await TransactionService(db).get(target.id)
    assert fetched is not None
    assert fetched.id == target.id


@pytest.mark.asyncio
async def test_update_transaction_description(db):
    await _seed(db)
    txns = await TransactionService(db).list()
    target = txns[0]
    updated = await TransactionService(db).update(target.id, description="Updated Description")
    assert updated.description == "Updated Description"


@pytest.mark.asyncio
async def test_update_nonexistent_transaction_returns_none(db):
    result = await TransactionService(db).update(uuid.uuid4(), description="Ghost")
    assert result is None


@pytest.mark.asyncio
async def test_delete_transaction_returns_true(db):
    await _seed(db)
    txns = await TransactionService(db).list()
    target = txns[0]
    deleted = await TransactionService(db).delete(target.id)
    assert deleted is True
    assert await TransactionService(db).get(target.id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_transaction_returns_false(db):
    assert await TransactionService(db).delete(uuid.uuid4()) is False
