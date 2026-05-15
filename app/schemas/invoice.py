import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.schemas.line_item import LineItemResponse


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    vendor_name: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    invoice_number: Optional[str] = None
    total_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    tax_amount: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime
    line_items: list[LineItemResponse] = []

    model_config = {"from_attributes": True}


class InvoiceUpdate(BaseModel):
    vendor_name: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    invoice_number: Optional[str] = None
    total_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    tax_amount: Optional[Decimal] = None


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int
    page: int
    page_size: int
