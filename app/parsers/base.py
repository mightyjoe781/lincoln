from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


class ParseError(Exception):
    pass


@dataclass
class ParsedLineItem:
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = None


@dataclass
class InvoiceParseResult:
    vendor_name: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    invoice_number: str | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    tax_amount: Decimal | None = None
    raw_text: str = ""
    line_items: list[ParsedLineItem] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)


@dataclass
class TransactionParseResult:
    transaction_date: date | None = None
    description: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    debit_credit: str | None = None
    balance: Decimal | None = None
    reference: str | None = None
    parse_warnings: list[str] = field(default_factory=list)


class InvoiceParser(Protocol):
    def parse(self, data: bytes) -> InvoiceParseResult: ...


class StatementParser(Protocol):
    def parse(self, data: bytes) -> list[TransactionParseResult]: ...
