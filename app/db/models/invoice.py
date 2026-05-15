import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String, nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_vector: Mapped[str | None] = mapped_column(postgresql.TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    document: Mapped["Document"] = relationship("Document", back_populates="invoices")
    line_items: Mapped[list["LineItem"]] = relationship("LineItem", back_populates="invoice", cascade="all, delete-orphan")
