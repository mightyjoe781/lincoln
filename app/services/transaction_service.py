import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.transaction import Transaction


class TransactionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, txn_id: uuid.UUID) -> Transaction | None:
        return await self.db.get(Transaction, txn_id)

    async def list(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        currency: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "date",
        sort_order: str = "desc",
    ) -> list[Transaction]:
        q = select(Transaction)
        if date_from:
            q = q.where(Transaction.transaction_date >= date_from)
        if date_to:
            q = q.where(Transaction.transaction_date <= date_to)
        if amount_min is not None:
            q = q.where(Transaction.amount >= amount_min)
        if amount_max is not None:
            q = q.where(Transaction.amount <= amount_max)
        if currency:
            q = q.where(Transaction.currency == currency.upper())

        order_col = {
            "date": Transaction.transaction_date,
            "amount": Transaction.amount,
        }.get(sort_by, Transaction.transaction_date)
        q = q.order_by(order_col.desc() if sort_order == "desc" else order_col.asc())
        q = q.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.scalars(q)
        return list(result)

    async def update(self, txn_id: uuid.UUID, **kwargs) -> Transaction | None:
        txn = await self.db.get(Transaction, txn_id)
        if not txn:
            return None
        for k, v in kwargs.items():
            if hasattr(txn, k):
                setattr(txn, k, v)
        await self.db.commit()
        await self.db.refresh(txn)
        return txn

    async def delete(self, txn_id: uuid.UUID) -> bool:
        txn = await self.db.get(Transaction, txn_id)
        if not txn:
            return False
        await self.db.delete(txn)
        await self.db.commit()
        return True
