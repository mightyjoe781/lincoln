import uuid
from decimal import Decimal

from app.db.models.document import Document
from app.db.models.invoice import Invoice
from app.db.models.line_item import LineItem
from app.db.models.transaction import Transaction
from app.db.models.user import User

# ── Document ──────────────────────────────────────────────────────────────


def test_document_model_defaults():
    doc = Document(
        filename="x.pdf",
        original_name="x.pdf",
        file_type="pdf_invoice",
        mime_type="application/pdf",
        file_size=1024,
        file_path="/tmp/x.pdf",
        checksum="abc123",
    )
    assert doc.status == "pending"
    assert doc.id is None


def test_document_status_defaults_to_pending():
    doc = Document(
        filename="x.pdf",
        original_name="x.pdf",
        file_type="pdf_invoice",
        mime_type="application/pdf",
        file_size=1024,
        file_path="/tmp/x.pdf",
        checksum="abc",
    )
    assert doc.status == "pending"


def test_document_id_is_none_before_db_flush():
    doc = Document(
        filename="y.csv",
        original_name="y.csv",
        file_type="csv_statement",
        mime_type="text/csv",
        file_size=512,
        file_path="/tmp/y.csv",
        checksum="def",
    )
    assert doc.id is None


def test_document_error_message_defaults_to_none():
    doc = Document(
        filename="z.pdf",
        original_name="z.pdf",
        file_type="pdf_invoice",
        mime_type="application/pdf",
        file_size=100,
        file_path="/tmp/z.pdf",
        checksum="ghi",
    )
    assert doc.error_message is None


# ── Invoice ────────────────────────────────────────────────────────────────


def test_invoice_all_optional_fields_default_to_none():
    inv = Invoice(document_id=uuid.uuid4())
    assert inv.vendor_name is None
    assert inv.invoice_date is None
    assert inv.total_amount is None
    assert inv.currency is None
    assert inv.tax_amount is None
    assert inv.invoice_number is None


def test_invoice_accepts_decimal_amounts():
    inv = Invoice(
        document_id=uuid.uuid4(),
        total_amount=Decimal("1234.5678"),
        tax_amount=Decimal("123.45"),
    )
    assert inv.total_amount == Decimal("1234.5678")


def test_invoice_document_id_is_stored():
    doc_id = uuid.uuid4()
    inv = Invoice(document_id=doc_id)
    assert inv.document_id == doc_id


# ── Transaction ────────────────────────────────────────────────────────────


def test_transaction_optional_fields_default_to_none():
    txn = Transaction(document_id=uuid.uuid4())
    assert txn.transaction_date is None
    assert txn.description is None
    assert txn.amount is None
    assert txn.currency is None
    assert txn.debit_credit is None
    assert txn.balance is None
    assert txn.reference is None


def test_transaction_accepts_negative_amount():
    txn = Transaction(document_id=uuid.uuid4(), amount=Decimal("-500.00"))
    assert txn.amount == Decimal("-500.00")


# ── LineItem ───────────────────────────────────────────────────────────────


def test_line_item_all_fields_optional():
    li = LineItem(invoice_id=uuid.uuid4())
    assert li.description is None
    assert li.quantity is None
    assert li.unit_price is None
    assert li.total is None
    assert li.currency is None


# ── User ──────────────────────────────────────────────────────────────────


def test_user_model_fields_exist():
    user = User(email="test@example.com", hashed_password="$2b$12$fakehash")
    assert user.email == "test@example.com"
    assert user.hashed_password == "$2b$12$fakehash"
    # id is populated by SQLAlchemy at flush/commit, not at Python construction
    assert user.id is None
