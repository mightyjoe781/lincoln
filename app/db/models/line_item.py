import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="line_items")
