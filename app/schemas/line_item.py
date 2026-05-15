import uuid
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class LineItemResponse(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    total: Optional[Decimal] = None
    currency: Optional[str] = None

    model_config = {"from_attributes": True}
