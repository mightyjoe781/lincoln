import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.invoice import Invoice


class InvoiceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, invoice_id: uuid.UUID) -> Invoice | None:
        result = await self.db.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(selectinload(Invoice.line_items))
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        vendor_name: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        currency: str | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "date",
        sort_order: str = "desc",
    ) -> list[Invoice]:
        stmt = select(Invoice).options(selectinload(Invoice.line_items))
        if q:
            stmt = stmt.where(Invoice.search_vector.op('@@')(func.plainto_tsquery('english', q)))
        if vendor_name:
            stmt = stmt.where(Invoice.vendor_name.ilike(f"%{vendor_name}%"))
        if date_from:
            stmt = stmt.where(Invoice.invoice_date >= date_from)
        if date_to:
            stmt = stmt.where(Invoice.invoice_date <= date_to)
        if amount_min is not None:
            stmt = stmt.where(Invoice.total_amount >= amount_min)
        if amount_max is not None:
            stmt = stmt.where(Invoice.total_amount <= amount_max)
        if currency:
            stmt = stmt.where(Invoice.currency == currency.upper())

        order_col = {
            "date": Invoice.invoice_date,
            "amount": Invoice.total_amount,
            "vendor": Invoice.vendor_name,
        }.get(sort_by, Invoice.invoice_date)
        stmt = stmt.order_by(order_col.desc() if sort_order == "desc" else order_col.asc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.scalars(stmt)
        return list(result)

    async def update(self, invoice_id: uuid.UUID, **kwargs) -> Invoice | None:
        invoice = await self.db.get(Invoice, invoice_id)
        if not invoice:
            return None
        for k, v in kwargs.items():
            if hasattr(invoice, k):
                setattr(invoice, k, v)
        await self.db.commit()
        await self.db.refresh(invoice)
        return invoice

    async def delete(self, invoice_id: uuid.UUID) -> bool:
        invoice = await self.db.get(Invoice, invoice_id)
        if not invoice:
            return False
        await self.db.delete(invoice)
        await self.db.commit()
        return True
