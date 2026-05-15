import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models.invoice import Invoice
from app.db.models.user import User
from app.schemas.invoice import InvoiceListResponse, InvoiceResponse, InvoiceUpdate
from app.services.invoice_service import InvoiceService

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    vendor_name: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    amount_min: Optional[float] = Query(None),
    amount_max: Optional[float] = Query(None),
    currency: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("date", pattern="^(date|amount|vendor)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    svc = InvoiceService(db)
    items = await svc.list(
        vendor_name=vendor_name,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        currency=currency,
        q=q,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    # count with same filters (no pagination)
    count_stmt = select(func.count()).select_from(Invoice)
    if q:
        count_stmt = count_stmt.where(
            Invoice.search_vector.op("@@")(func.plainto_tsquery("english", q))
        )
    if vendor_name:
        count_stmt = count_stmt.where(Invoice.vendor_name.ilike(f"%{vendor_name}%"))
    if date_from:
        count_stmt = count_stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        count_stmt = count_stmt.where(Invoice.invoice_date <= date_to)
    if amount_min is not None:
        count_stmt = count_stmt.where(Invoice.total_amount >= amount_min)
    if amount_max is not None:
        count_stmt = count_stmt.where(Invoice.total_amount <= amount_max)
    if currency:
        count_stmt = count_stmt.where(Invoice.currency == currency.upper())
    total = await db.scalar(count_stmt) or 0

    return InvoiceListResponse(
        items=[InvoiceResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    svc = InvoiceService(db)
    invoice = await svc.get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return InvoiceResponse.model_validate(invoice)


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID,
    body: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = InvoiceService(db)
    updated = await svc.update(invoice_id, **body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return InvoiceResponse.model_validate(updated)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = InvoiceService(db)
    deleted = await svc.delete(invoice_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
