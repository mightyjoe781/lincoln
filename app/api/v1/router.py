from fastapi import APIRouter

from app.api.v1.documents import router as documents_router
from app.api.v1.invoices import router as invoices_router
from app.api.v1.transactions import router as transactions_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(documents_router)
v1_router.include_router(invoices_router)
v1_router.include_router(transactions_router)
