import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models.user import User
from app.db.models.transaction import Transaction
from app.schemas.transaction import TransactionListResponse, TransactionResponse, TransactionUpdate
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    amount_min: Optional[float] = Query(None),
    amount_max: Optional[float] = Query(None),
    currency: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("date", pattern="^(date|amount)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    svc = TransactionService(db)
    items = await svc.list(
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
    count_stmt = select(func.count()).select_from(Transaction)
    if q:
        count_stmt = count_stmt.where(Transaction.search_vector.op('@@')(func.plainto_tsquery('english', q)))
    if date_from:
        count_stmt = count_stmt.where(Transaction.transaction_date >= date_from)
    if date_to:
        count_stmt = count_stmt.where(Transaction.transaction_date <= date_to)
    if amount_min is not None:
        count_stmt = count_stmt.where(Transaction.amount >= amount_min)
    if amount_max is not None:
        count_stmt = count_stmt.where(Transaction.amount <= amount_max)
    if currency:
        count_stmt = count_stmt.where(Transaction.currency == currency.upper())
    total = await db.scalar(count_stmt) or 0

    return TransactionListResponse(
        items=[TransactionResponse.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{txn_id}", response_model=TransactionResponse)
async def get_transaction(txn_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    svc = TransactionService(db)
    txn = await svc.get(txn_id)
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return TransactionResponse.model_validate(txn)


@router.patch("/{txn_id}", response_model=TransactionResponse)
async def update_transaction(
    txn_id: uuid.UUID,
    body: TransactionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = TransactionService(db)
    updated = await svc.update(txn_id, **body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return TransactionResponse.model_validate(updated)


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(txn_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    svc = TransactionService(db)
    deleted = await svc.delete(txn_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
