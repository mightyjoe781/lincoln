# Lincoln — Test Coverage Improvement Plan

## Current State Assessment

### What Exists

| File | Tests | What's Covered |
|------|-------|----------------|
| `tests/test_health.py` | 1 | `GET /health` happy path only |
| `tests/unit/test_models.py` | 1 | `Document` default field values |
| `tests/unit/test_storage.py` | 3 | `LocalFileStorage.save`, `delete`, `exists` happy paths |
| `tests/unit/parsers/test_normalizers.py` | 16 (parametrized) | `parse_date`, `parse_amount`, `normalize_currency` — main paths + None/empty |
| `tests/unit/parsers/test_csv_statement_parser.py` | 4 | Standard CSV, messy dates, empty body, missing column |
| `tests/unit/parsers/test_pdf_invoice_parser.py` | 2 | Corrupted bytes, empty bytes — both raise `ParseError` |
| `tests/unit/services/test_document_service.py` | 4 | Upload → pending status, task enqueued, duplicate detection, metadata stored |
| `tests/unit/services/test_invoice_service.py` | 3 | Filter by vendor, date range, pagination |
| `tests/unit/services/test_transaction_service.py` | 1 | Date-range filter |
| `tests/integration/` | **0** | Nothing — directory is empty |

**Total tests: ~35.** Zero API route tests. Zero integration tests. Zero auth tests.

### Estimated Line Coverage Per Module (before this plan)

| Module | Estimated Coverage | Biggest Uncovered Paths |
|--------|--------------------|------------------------|
| `app/parsers/normalizers.py` | ~80% | Whitespace-only strings, non-Latin scripts, negative amounts, parenthetical negatives |
| `app/parsers/csv_statement.py` | ~65% | >1 000-row file, all-null rows, BOM handling, `debit_credit` parsing branches |
| `app/parsers/pdf_invoice.py` | ~40% | Password-protected PDF, image-only PDF, line-item extraction, every regex branch |
| `app/parsers/registry.py` | ~50% | Unknown mime type → `ParseError`, `get_file_type` unknown fallback |
| `app/parsers/base.py` | ~70% | `InvoiceParser`/`StatementParser` Protocol stubs |
| `app/services/document_service.py` | ~60% | `get`, `list`, `delete`, `_persist_parsed_data` (both branches), storage error on save |
| `app/services/invoice_service.py` | ~40% | `get`, `update`, `delete`, amount filters, currency filter, sort, full-text `q` |
| `app/services/transaction_service.py` | ~20% | `get`, `update`, `delete`, amount/currency/q filters, sort |
| `app/storage/local.py` | ~75% | `read`, permission errors, disk-full simulation |
| `app/core/security.py` | **0%** | `hash_password`, `verify_password`, `create_access_token`, `decode_token` |
| `app/api/v1/auth.py` | **0%** | Both endpoints, registration token guard, 409 conflict |
| `app/api/v1/documents.py` | **~5%** | Only reached via `test_health.py` app import; no route tests |
| `app/api/v1/invoices.py` | **0%** | All routes untested |
| `app/api/v1/transactions.py` | **0%** | All routes untested |
| `app/api/deps.py` | **0%** | `get_current_user`, expired-token path |
| `app/worker/tasks.py` | **0%** | `parse_document_task`, `_parse_document`, `_persist_parsed` |
| `app/db/models/*` | ~10% | Only `Document` defaults; Invoice/Transaction/LineItem/User untested |

### Biggest Gaps Ranked by Risk

1. **Auth (security.py, auth.py, deps.py)** — zero coverage; a bug here locks out all users or allows unauthorised access to every write endpoint.
2. **API routes (documents, invoices, transactions)** — all HTTP contract is untested; regressions will be invisible in CI.
3. **Worker tasks (tasks.py)** — the entire parse pipeline runs here; zero tests means a broken parser goes undetected until production.
4. **TransactionService** — only 1 of 6 methods tested; filters, sort, update, and delete are live but dark.
5. **PDF parser internals** — only two negative cases exist; the regex extraction logic, line-item parser, and real-PDF smoke tests are absent.
6. **Storage error paths** — no test verifies behaviour when the filesystem is unwritable or the file is missing on read.

---

## Phase 1 — Fill Unit Test Gaps

**Priority: P1**
**Target coverage after phase:** normalizers ≥ 95%, csv_statement ≥ 90%, pdf_invoice ≥ 70%, storage ≥ 90%, models ≥ 80%, security ≥ 95%

### Task Checklist

- [ ] `tests/unit/parsers/test_normalizers.py` — add edge cases (this file)
- [ ] `tests/unit/parsers/test_csv_statement_parser.py` — add volume/edge cases
- [ ] `tests/unit/parsers/test_pdf_invoice_parser.py` — add real-PDF smoke tests and edge cases
- [ ] `tests/unit/parsers/test_registry.py` — new file
- [ ] `tests/unit/test_storage.py` — add error-path tests
- [ ] `tests/unit/test_models.py` — add all model classes
- [ ] `tests/unit/test_security.py` — new file (auth unit tests)
- [ ] `tests/unit/services/test_transaction_service.py` — fill remaining methods
- [ ] `tests/unit/services/test_invoice_service.py` — fill remaining methods
- [ ] `tests/unit/services/test_document_service.py` — fill get/list/delete

---

### 1.1 Normalizer Edge Cases

**File:** `tests/unit/parsers/test_normalizers.py`

```python
# ── parse_date edge cases ──────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("   ", None),                          # whitespace-only
    ("\t\n", None),                         # tabs and newlines
    ("00/00/0000", None),                   # structurally valid but nonsensical
    ("2024-02-30", None),                   # impossible calendar date
    ("15 May 2024", date(2024, 5, 15)),     # natural language with space
    ("2024/05/15", date(2024, 5, 15)),      # forward-slash ISO variant
    ("١٥/٠٥/٢٠٢٤", None),                  # Arabic-Indic digits — returns None gracefully
])
def test_parse_date_edge_cases(raw, expected):
    assert parse_date(raw) == expected


# ── parse_amount edge cases ───────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("   ", None),                          # whitespace-only
    ("(1,234.56)", None),                   # parenthetical negative — not yet supported; assert None not crash
    ("-1234.56", Decimal("-1234.56")),       # explicit negative
    ("0.00", Decimal("0.00")),              # zero
    ("1" * 20, None),                       # absurdly large non-numeric-ish string
    ("1.234", Decimal("1.234")),            # ambiguous European vs decimal — falls through to Decimal directly
    ("CHF 9'999.00", None),                 # Swiss apostrophe thousands separator — currently unsupported; assert no crash
])
def test_parse_amount_edge_cases(raw, expected):
    assert parse_amount(raw) == expected


# ── normalize_currency edge cases ─────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("   ", None),                          # whitespace-only
    ("A$", "AUD"),                          # multi-char symbol
    ("C$", "CAD"),                          # multi-char symbol
    ("£", "GBP"),
    ("¥", "JPY"),
    ("₹", "INR"),
    ("XYZ", None),                          # unknown ISO code
    ("DOLLAR", None),                       # word-form — not recognised
    ("sgd", "SGD"),                         # lowercase known ISO
    ("hkd", "HKD"),
])
def test_normalize_currency_edge_cases(raw, expected):
    assert normalize_currency(raw) == expected
```

---

### 1.2 CSV Parser Edge Cases

**File:** `tests/unit/parsers/test_csv_statement_parser.py`

```python
import io, csv
from decimal import Decimal
from app.parsers.csv_statement import CsvStatementParser
from app.parsers.base import ParseError


def test_parse_header_only_returns_empty_list():
    """A file with headers but zero data rows should return []."""
    data = b"date,description,amount\n"
    rows = CsvStatementParser().parse(data)
    assert rows == []


def test_parse_all_null_row_is_skipped():
    """A row where every cell is empty should be silently dropped."""
    data = b"date,description,amount\n,,,\n2024-01-01,Salary,1000\n"
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1
    assert rows[0].description == "Salary"


def test_parse_large_csv_returns_correct_count():
    """Parser should handle >1 000 rows without error or truncation."""
    header = "date,description,amount\n"
    row = "2024-01-01,Test,100.00\n"
    data = (header + row * 1100).encode()
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1100


def test_parse_bom_prefix_is_handled():
    """UTF-8 BOM (\\xef\\xbb\\xbf) should be stripped and not break column mapping."""
    data = b"\xef\xbb\xbfdate,description,amount\n2024-01-01,BOM Test,50.00\n"
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1
    assert rows[0].amount == Decimal("50.00")


def test_parse_debit_credit_variants():
    """All debit/credit shorthand values should normalise correctly."""
    rows_data = [
        ("DR", "debit"), ("dr", "debit"), ("D", "debit"),
        ("CR", "credit"), ("cr", "credit"), ("C", "credit"),
        ("DEBIT", "debit"), ("CREDIT", "credit"),
    ]
    for raw, expected in rows_data:
        csv_bytes = (
            f"date,description,amount,debit_credit\n"
            f"2024-01-01,Test,100,{raw}\n"
        ).encode()
        rows = CsvStatementParser().parse(csv_bytes)
        assert rows[0].debit_credit == expected, f"Failed for raw={raw!r}"


def test_parse_column_aliases_recognised():
    """Alternative column names (narration, trans_date, txn_id) map correctly."""
    data = b"trans_date,narration,transaction_amount,ccy,txn_id\n2024-03-01,Rent,-1500,USD,REF001\n"
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1
    assert rows[0].description == "Rent"
    assert rows[0].currency == "USD"
    assert rows[0].reference == "REF001"


def test_parse_empty_bytes_returns_empty_list():
    """Completely empty bytes (no headers at all) should return []."""
    rows = CsvStatementParser().parse(b"")
    assert rows == []


def test_parse_amount_warning_added_for_unparseable():
    """An unparseable amount should NOT raise but should add a warning to the row."""
    data = b"date,description,amount\n2024-01-01,Test,NOT_A_NUMBER\n"
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1
    assert rows[0].amount is None
    assert any("unparseable amount" in w for w in rows[0].parse_warnings)
```

---

### 1.3 PDF Parser Edge Cases

**File:** `tests/unit/parsers/test_pdf_invoice_parser.py`

```python
import io
import pytest
from unittest.mock import patch, MagicMock
from app.parsers.pdf_invoice import PdfInvoiceParser
from app.parsers.base import ParseError


def test_parse_password_protected_pdf_raises_parse_error():
    """pdfplumber raises when it encounters an encrypted PDF it cannot open."""
    # Simulate pdfplumber raising on open
    with patch("pdfplumber.open", side_effect=Exception("file has not been decrypted")):
        with pytest.raises(ParseError, match="Cannot open PDF"):
            PdfInvoiceParser().parse(b"%PDF-1.4 fake encrypted content")


def test_parse_image_only_pdf_returns_result_with_empty_text():
    """An image-only scan has no extractable text; parser should return a result
    with raw_text='' and all fields None rather than crashing."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = None   # image-only page
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = PdfInvoiceParser().parse(b"%PDF-fake")

    assert result.raw_text == ""
    assert result.vendor_name is None
    assert result.total_amount is None
    assert "vendor_name not found" in result.parse_warnings


def test_parse_pdf_with_vendor_and_total():
    """Verify field extraction from a PDF whose text contains known patterns."""
    fake_text = (
        "ACME Corp Inc\n"
        "Invoice Date: 2024-05-15\n"
        "Due Date: 2024-06-15\n"
        "Invoice #: INV-0042\n"
        "Total: $1,500.00\n"
        "Tax: $150.00\n"
    )
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fake_text
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = PdfInvoiceParser().parse(b"%PDF-fake")

    from datetime import date
    from decimal import Decimal
    assert result.invoice_number == "INV-0042"
    assert result.invoice_date == date(2024, 5, 15)
    assert result.due_date == date(2024, 6, 15)
    assert result.total_amount == Decimal("1500.00")
    assert result.tax_amount == Decimal("150.00")


def test_parse_pdf_line_item_extraction():
    """Lines matching <description><2+ spaces><amount> should be captured as line items."""
    fake_text = (
        "Consulting Services  800.00\n"
        "Software Licence  700.00\n"
        "Total: $1,500.00\n"
    )
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fake_text
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    from decimal import Decimal
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = PdfInvoiceParser().parse(b"%PDF-fake")

    assert len(result.line_items) == 2
    descriptions = [li.description for li in result.line_items]
    assert "Consulting Services" in descriptions
    assert "Software Licence" in descriptions
```

---

### 1.4 Parser Registry

**File:** `tests/unit/parsers/test_registry.py` (new file)

```python
import pytest
from app.parsers.registry import get_parser, get_file_type
from app.parsers.base import ParseError
from app.parsers.csv_statement import CsvStatementParser
from app.parsers.pdf_invoice import PdfInvoiceParser


def test_get_parser_csv():
    assert isinstance(get_parser("text/csv"), CsvStatementParser)


def test_get_parser_text_plain():
    assert isinstance(get_parser("text/plain"), CsvStatementParser)


def test_get_parser_pdf():
    assert isinstance(get_parser("application/pdf"), PdfInvoiceParser)


def test_get_parser_unknown_raises():
    with pytest.raises(ParseError, match="No parser for mime type"):
        get_parser("image/jpeg")


def test_get_file_type_csv():
    assert get_file_type("text/csv") == "csv_statement"


def test_get_file_type_pdf():
    assert get_file_type("application/pdf") == "pdf_invoice"


def test_get_file_type_unknown_returns_unknown():
    assert get_file_type("video/mp4") == "unknown"
```

---

### 1.5 Storage Error Paths

**File:** `tests/unit/test_storage.py`

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.storage.local import LocalFileStorage


@pytest.mark.asyncio
async def test_read_returns_correct_bytes(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    path = await storage.save(b"hello world", "test.txt", "hw123")
    content = await storage.read(path)
    assert content == b"hello world"


@pytest.mark.asyncio
async def test_exists_returns_false_for_missing_file(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    assert not await storage.exists(str(tmp_path / "ghost.pdf"))


@pytest.mark.asyncio
async def test_delete_nonexistent_file_does_not_raise(tmp_path):
    """Deleting a path that never existed should be a no-op."""
    storage = LocalFileStorage(base_dir=tmp_path)
    await storage.delete(str(tmp_path / "nonexistent.pdf"))  # must not raise


@pytest.mark.asyncio
async def test_save_permission_error_propagates(tmp_path):
    """If the filesystem refuses the write, the OSError should bubble up."""
    storage = LocalFileStorage(base_dir=tmp_path)
    dest = tmp_path / "abc123.pdf"
    with patch.object(Path, "write_bytes", side_effect=PermissionError("read-only filesystem")):
        with pytest.raises(PermissionError):
            await storage.save(b"data", "invoice.pdf", "abc123")


@pytest.mark.asyncio
async def test_base_dir_created_if_missing(tmp_path):
    """Constructor must create missing parent directories."""
    new_dir = tmp_path / "deep" / "nested" / "dir"
    assert not new_dir.exists()
    LocalFileStorage(base_dir=new_dir)
    assert new_dir.exists()
```

---

### 1.6 Model Tests

**File:** `tests/unit/test_models.py`

```python
import uuid
from decimal import Decimal
from datetime import date, datetime
from app.db.models.document import Document
from app.db.models.invoice import Invoice
from app.db.models.transaction import Transaction
from app.db.models.line_item import LineItem
from app.db.models.user import User


# ── Document ──────────────────────────────────────────────────────────────

def test_document_status_defaults_to_pending():
    doc = Document(filename="x.pdf", original_name="x.pdf", file_type="pdf_invoice",
                   mime_type="application/pdf", file_size=1024, file_path="/tmp/x.pdf", checksum="abc")
    assert doc.status == "pending"


def test_document_id_is_none_before_db_flush():
    doc = Document(filename="y.csv", original_name="y.csv", file_type="csv_statement",
                   mime_type="text/csv", file_size=512, file_path="/tmp/y.csv", checksum="def")
    assert doc.id is None


def test_document_error_message_defaults_to_none():
    doc = Document(filename="z.pdf", original_name="z.pdf", file_type="pdf_invoice",
                   mime_type="application/pdf", file_size=100, file_path="/tmp/z.pdf", checksum="ghi")
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
    inv = Invoice(document_id=uuid.uuid4(), total_amount=Decimal("1234.5678"), tax_amount=Decimal("123.45"))
    assert inv.total_amount == Decimal("1234.5678")


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
    assert user.id is None   # not yet flushed
```

---

### 1.7 Security / Auth Unit Tests

**File:** `tests/unit/test_security.py` (new file)

```python
import time
import pytest
from datetime import datetime, timedelta
from jose import jwt, JWTError
from unittest.mock import patch

from app.core.security import hash_password, verify_password, create_access_token, decode_token
from app.core.config import settings


# ── Password hashing ───────────────────────────────────────────────────────

def test_hash_password_returns_bcrypt_string():
    h = hash_password("secret123")
    assert h.startswith("$2b$") or h.startswith("$2a$")


def test_hash_password_is_not_plaintext():
    h = hash_password("secret123")
    assert h != "secret123"


def test_verify_password_correct():
    h = hash_password("mypassword")
    assert verify_password("mypassword", h) is True


def test_verify_password_wrong():
    h = hash_password("mypassword")
    assert verify_password("wrongpassword", h) is False


def test_hash_is_not_deterministic():
    """Two hashes of the same password should differ (salt randomness)."""
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2


# ── Token creation ────────────────────────────────────────────────────────

def test_create_access_token_returns_string():
    token = create_access_token("user@example.com")
    assert isinstance(token, str)
    assert len(token) > 10


def test_create_access_token_encodes_subject():
    token = create_access_token("user@example.com")
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == "user@example.com"


def test_create_access_token_has_expiry():
    token = create_access_token("user@example.com")
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert "exp" in payload
    assert payload["exp"] > time.time()


# ── Token decoding ────────────────────────────────────────────────────────

def test_decode_token_returns_subject():
    token = create_access_token("alice@example.com")
    assert decode_token(token) == "alice@example.com"


def test_decode_token_raises_on_tampered_signature():
    token = create_access_token("alice@example.com")
    tampered = token[:-4] + "XXXX"
    with pytest.raises(JWTError):
        decode_token(tampered)


def test_decode_token_raises_on_expired():
    """Forge a token with exp in the past."""
    past = datetime.utcnow() - timedelta(seconds=1)
    expired_token = jwt.encode(
        {"sub": "alice@example.com", "exp": past},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(JWTError):
        decode_token(expired_token)


def test_decode_token_raises_on_missing_sub():
    """A valid-signature token with no 'sub' claim should raise JWTError."""
    token = jwt.encode(
        {"exp": datetime.utcnow() + timedelta(hours=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(JWTError, match="missing sub"):
        decode_token(token)
```

---

### 1.8 Service Gap Fill — DocumentService

**File:** `tests/unit/services/test_document_service.py`

```python
# Add these tests to the existing file

@pytest.mark.asyncio
async def test_get_existing_document(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    csv_bytes = b"date,description,amount\n2024-01-01,Test,100.00\n"
    created = await svc.upload(csv_bytes, "test.csv", "text/csv")
    fetched = await svc.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_get_nonexistent_document_returns_none(db, mock_celery_task):
    import uuid
    svc = DocumentService(db, MockStorage())
    result = await svc.get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_returns_documents(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    for i in range(3):
        await svc.upload(f"date,description,amount\n2024-01-01,T{i},{i*100}\n".encode(), f"f{i}.csv", "text/csv")
    docs = await svc.list(page=1, page_size=10)
    assert len(docs) >= 3


@pytest.mark.asyncio
async def test_list_pagination_second_page(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    for i in range(5):
        await svc.upload(f"date,description,amount\n2024-01-{i+1:02d},T,{i}\n".encode(), f"p{i}.csv", "text/csv")
    page1 = await svc.list(page=1, page_size=2)
    page2 = await svc.list(page=2, page_size=2)
    ids_p1 = {d.id for d in page1}
    ids_p2 = {d.id for d in page2}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_delete_existing_document(db, mock_celery_task):
    svc = DocumentService(db, MockStorage())
    csv_bytes = b"date,description,amount\n2024-01-01,Del,1.00\n"
    doc = await svc.upload(csv_bytes, "del.csv", "text/csv")
    result = await svc.delete(doc.id)
    assert result is True
    assert await svc.get(doc.id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_document_returns_false(db, mock_celery_task):
    import uuid
    svc = DocumentService(db, MockStorage())
    assert await svc.delete(uuid.uuid4()) is False
```

---

### 1.9 Service Gap Fill — InvoiceService and TransactionService

**File:** `tests/unit/services/test_invoice_service.py`

```python
# Add to existing file

@pytest.mark.asyncio
async def test_get_invoice_by_id(db):
    await _seed(db)
    all_invoices = await InvoiceService(db).list()
    first = all_invoices[0]
    fetched = await InvoiceService(db).get(first.id)
    assert fetched is not None
    assert fetched.id == first.id


@pytest.mark.asyncio
async def test_get_nonexistent_invoice_returns_none(db):
    import uuid
    result = await InvoiceService(db).get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_amount_range(db):
    await _seed(db)
    results = await InvoiceService(db).list(amount_min=600, amount_max=1200)
    assert all(600 <= float(r.total_amount) <= 1200 for r in results)


@pytest.mark.asyncio
async def test_list_currency_filter(db):
    await _seed(db)
    results = await InvoiceService(db).list(currency="EUR")
    assert all(r.currency == "EUR" for r in results)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_list_empty_result_returns_empty_list(db):
    await _seed(db)
    results = await InvoiceService(db).list(vendor_name="ZZZ_NO_MATCH_XYZ")
    assert results == []


@pytest.mark.asyncio
async def test_update_invoice_vendor_name(db):
    await _seed(db)
    invoices = await InvoiceService(db).list()
    target = invoices[0]
    updated = await InvoiceService(db).update(target.id, vendor_name="Updated Corp")
    assert updated is not None
    assert updated.vendor_name == "Updated Corp"


@pytest.mark.asyncio
async def test_update_nonexistent_invoice_returns_none(db):
    import uuid
    result = await InvoiceService(db).update(uuid.uuid4(), vendor_name="Ghost")
    assert result is None


@pytest.mark.asyncio
async def test_delete_invoice(db):
    await _seed(db)
    invoices = await InvoiceService(db).list()
    target = invoices[0]
    deleted = await InvoiceService(db).delete(target.id)
    assert deleted is True
    assert await InvoiceService(db).get(target.id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_invoice_returns_false(db):
    import uuid
    assert await InvoiceService(db).delete(uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_list_sort_by_amount_asc(db):
    await _seed(db)
    results = await InvoiceService(db).list(sort_by="amount", sort_order="asc")
    amounts = [float(r.total_amount) for r in results if r.total_amount is not None]
    assert amounts == sorted(amounts)
```

**File:** `tests/unit/services/test_transaction_service.py`

```python
# Extend the existing file

@pytest.mark.asyncio
async def test_list_amount_range(db):
    await _seed(db)
    results = await TransactionService(db).list(amount_min=-2000, amount_max=0)
    assert all(-2000 <= float(r.amount) <= 0 for r in results if r.amount is not None)


@pytest.mark.asyncio
async def test_list_sort_by_amount_desc(db):
    await _seed(db)
    results = await TransactionService(db).list(sort_by="amount", sort_order="desc")
    amounts = [float(r.amount) for r in results if r.amount is not None]
    assert amounts == sorted(amounts, reverse=True)


@pytest.mark.asyncio
async def test_get_transaction_by_id(db):
    await _seed(db)
    all_txns = await TransactionService(db).list()
    target = all_txns[0]
    fetched = await TransactionService(db).get(target.id)
    assert fetched is not None
    assert fetched.id == target.id


@pytest.mark.asyncio
async def test_get_nonexistent_transaction_returns_none(db):
    import uuid
    result = await TransactionService(db).get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_update_transaction_description(db):
    await _seed(db)
    txns = await TransactionService(db).list()
    target = txns[0]
    updated = await TransactionService(db).update(target.id, description="Updated Description")
    assert updated.description == "Updated Description"


@pytest.mark.asyncio
async def test_update_nonexistent_transaction_returns_none(db):
    import uuid
    result = await TransactionService(db).update(uuid.uuid4(), description="Ghost")
    assert result is None


@pytest.mark.asyncio
async def test_delete_transaction(db):
    await _seed(db)
    txns = await TransactionService(db).list()
    target = txns[0]
    deleted = await TransactionService(db).delete(target.id)
    assert deleted is True
    assert await TransactionService(db).get(target.id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_transaction_returns_false(db):
    import uuid
    assert await TransactionService(db).delete(uuid.uuid4()) is False
```

---

## Phase 2 — API Route Tests

**Priority: P1**
**Target coverage after phase:** all `app/api/v1/*` modules ≥ 85%, `app/api/deps.py` ≥ 90%

All tests in this phase live under `tests/unit/api/` and use the `client` fixture from `tests/conftest.py` with auth helpers defined below.

### Setup: auth helpers

Create `tests/unit/api/conftest.py`:

```python
import pytest
from app.core.security import create_access_token, hash_password
from app.db.models.user import User


@pytest.fixture
async def auth_headers(db) -> dict:
    """Register a test user and return Bearer auth headers."""
    user = User(email="tester@lincoln.test", hashed_password=hash_password("testpass123"))
    db.add(user)
    await db.commit()
    token = create_access_token("tester@lincoln.test")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def expired_auth_headers() -> dict:
    from datetime import datetime, timedelta
    from jose import jwt
    from app.core.config import settings
    past = datetime.utcnow() - timedelta(seconds=1)
    token = jwt.encode({"sub": "old@example.com", "exp": past}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return {"Authorization": f"Bearer {token}"}
```

### Task Checklist

- [ ] `tests/unit/api/test_auth.py` — new file
- [ ] `tests/unit/api/test_documents.py` — new file
- [ ] `tests/unit/api/test_invoices.py` — new file
- [ ] `tests/unit/api/test_transactions.py` — new file
- [ ] `tests/unit/api/conftest.py` — new file

---

### 2.1 Auth Route Tests

**File:** `tests/unit/api/test_auth.py`

```python
import pytest
from httpx import AsyncClient


# ── POST /api/v1/auth/register ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={"email": "new@example.com", "password": "pass1234"})
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@example.com"


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client: AsyncClient):
    payload = {"email": "dup@example.com", "password": "pass1234"}
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_invalid_email_returns_422(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "pass1234"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_password_returns_422(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={"email": "a@b.com"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_with_valid_registration_token(client: AsyncClient, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "registration_token", "secret-token")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "gated@example.com", "password": "pass1234"},
        headers={"X-Registration-Token": "secret-token"},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_register_with_wrong_registration_token_returns_403(client: AsyncClient, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "registration_token", "secret-token")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "blocked@example.com", "password": "pass1234"},
        headers={"X-Registration-Token": "wrong-token"},
    )
    assert resp.status_code == 403


# ── POST /api/v1/auth/token ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={"email": "login@example.com", "password": "mypass"})
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "login@example.com", "password": "mypass"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={"email": "badpw@example.com", "password": "correct"})
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "badpw@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "ghost@example.com", "password": "any"},
    )
    assert resp.status_code == 401
```

---

### 2.2 Document Route Tests

**File:** `tests/unit/api/test_documents.py`

```python
import io
import pytest
from httpx import AsyncClient


# ── GET /api/v1/documents ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_documents_empty(client: AsyncClient):
    resp = await client.get("/api/v1/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_list_documents_pagination_params(client: AsyncClient):
    resp = await client.get("/api/v1/documents?page=1&page_size=5")
    assert resp.status_code == 200
    assert resp.json()["page"] == 1
    assert resp.json()["page_size"] == 5


@pytest.mark.asyncio
async def test_list_documents_invalid_page_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/documents?page=0")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_documents_page_size_too_large_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/documents?page_size=101")
    assert resp.status_code == 422


# ── GET /api/v1/documents/{id} ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_document_not_found_returns_404(client: AsyncClient):
    import uuid
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_document_invalid_uuid_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/documents/not-a-uuid")
    assert resp.status_code == 422


# ── POST /api/v1/documents/upload ────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_requires_auth(client: AsyncClient):
    csv_file = ("files", ("test.csv", b"date,description,amount\n2024-01-01,T,1\n", "text/csv"))
    resp = await client.post("/api/v1/documents/upload", files=[csv_file])
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_csv_returns_200(client: AsyncClient, auth_headers):
    csv_bytes = b"date,description,amount\n2024-01-01,Salary,5000\n"
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("bank.csv", csv_bytes, "text/csv"))],
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["created"] == 1
    assert body["duplicates"] == 0
    doc = body["results"][0]["document"]
    assert doc["status"] == "pending"
    assert doc["original_name"] == "bank.csv"


@pytest.mark.asyncio
async def test_upload_duplicate_csv_not_reprocessed(client: AsyncClient, auth_headers):
    csv_bytes = b"date,description,amount\n2024-01-01,DupTest,999\n"
    await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("dup.csv", csv_bytes, "text/csv"))],
        headers=auth_headers,
    )
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("dup2.csv", csv_bytes, "text/csv"))],
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["duplicates"] == 1
    assert body["created"] == 0


@pytest.mark.asyncio
async def test_upload_unsupported_mime_returns_422(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("image.png", b"\x89PNG\r\n", "image/png"))],
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_file_too_large_returns_413(client: AsyncClient, auth_headers, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_upload_size_bytes", 10)  # 10 bytes max
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("big.csv", b"date,description,amount\n2024-01-01,T,1\n", "text/csv"))],
        headers=auth_headers,
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_upload_multiple_files(client: AsyncClient, auth_headers):
    files = [
        ("files", ("a.csv", b"date,description,amount\n2024-01-01,A,1\n", "text/csv")),
        ("files", ("b.csv", b"date,description,amount\n2024-01-02,B,2\n", "text/csv")),
    ]
    resp = await client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
    assert resp.json()["created"] == 2


# ── DELETE /api/v1/documents/{id} ────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_document_requires_auth(client: AsyncClient):
    import uuid
    resp = await client.delete(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_nonexistent_document_returns_404(client: AsyncClient, auth_headers):
    import uuid
    resp = await client.delete(f"/api/v1/documents/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_existing_document_returns_204(client: AsyncClient, auth_headers):
    csv_bytes = b"date,description,amount\n2024-01-01,DelMe,1\n"
    upload_resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("del.csv", csv_bytes, "text/csv"))],
        headers=auth_headers,
    )
    doc_id = upload_resp.json()["results"][0]["document"]["id"]
    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert resp.status_code == 204
    # Confirm it's gone
    get_resp = await client.get(f"/api/v1/documents/{doc_id}")
    assert get_resp.status_code == 404


# ── Auth enforcement on GET (unauthenticated reads should still work) ──────

@pytest.mark.asyncio
async def test_list_documents_no_auth_allowed(client: AsyncClient):
    """GET /documents is public (no auth required per the route definition)."""
    resp = await client.get("/api/v1/documents")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_expired_token_returns_401(client: AsyncClient, expired_auth_headers):
    csv_bytes = b"date,description,amount\n2024-01-01,T,1\n"
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("exp.csv", csv_bytes, "text/csv"))],
        headers=expired_auth_headers,
    )
    assert resp.status_code == 401
```

---

### 2.3 Invoice Route Tests

**File:** `tests/unit/api/test_invoices.py`

```python
import uuid
import pytest
from datetime import date
from httpx import AsyncClient
from app.db.models.document import Document
from app.db.models.invoice import Invoice


async def _seed_invoice(db) -> Invoice:
    doc = Document(
        filename="inv_api.pdf", original_name="inv_api.pdf", file_type="pdf_invoice",
        mime_type="application/pdf", file_size=100, file_path="/tmp/inv_api.pdf",
        checksum=f"inv_api_{uuid.uuid4().hex}", status="done",
    )
    db.add(doc)
    await db.flush()
    inv = Invoice(
        document_id=doc.id, vendor_name="TestVendor", invoice_date=date(2024, 3, 1),
        total_amount=1000, currency="USD",
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return inv


# ── GET /api/v1/invoices ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_invoices_returns_200(client: AsyncClient):
    resp = await client.get("/api/v1/invoices")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body and "total" in body


@pytest.mark.asyncio
async def test_list_invoices_vendor_filter(client: AsyncClient, db):
    await _seed_invoice(db)
    resp = await client.get("/api/v1/invoices?vendor_name=TestVendor")
    assert resp.status_code == 200
    assert all("TestVendor" in i["vendor_name"] for i in resp.json()["items"])


@pytest.mark.asyncio
async def test_list_invoices_date_range_filter(client: AsyncClient, db):
    await _seed_invoice(db)
    resp = await client.get("/api/v1/invoices?date_from=2024-01-01&date_to=2024-12-31")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_invoices_amount_range_filter(client: AsyncClient, db):
    await _seed_invoice(db)
    resp = await client.get("/api/v1/invoices?amount_min=500&amount_max=2000")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_invoices_currency_filter(client: AsyncClient, db):
    await _seed_invoice(db)
    resp = await client.get("/api/v1/invoices?currency=USD")
    assert resp.status_code == 200
    assert all(i["currency"] == "USD" for i in resp.json()["items"])


@pytest.mark.asyncio
async def test_list_invoices_empty_result(client: AsyncClient):
    resp = await client.get("/api/v1/invoices?vendor_name=ZZZ_NO_MATCH")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_invoices_invalid_sort_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/invoices?sort_by=invalid")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_invoices_last_page_returns_partial_or_empty(client: AsyncClient, db):
    await _seed_invoice(db)
    resp = await client.get("/api/v1/invoices?page=9999&page_size=100")
    assert resp.status_code == 200
    # May be empty on a fresh DB with few items
    assert isinstance(resp.json()["items"], list)


# ── GET /api/v1/invoices/{id} ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_invoice_success(client: AsyncClient, db):
    inv = await _seed_invoice(db)
    resp = await client.get(f"/api/v1/invoices/{inv.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(inv.id)
    assert resp.json()["vendor_name"] == "TestVendor"


@pytest.mark.asyncio
async def test_get_invoice_not_found_returns_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/invoices/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_invoice_invalid_uuid_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/invoices/not-a-uuid")
    assert resp.status_code == 422


# ── PATCH /api/v1/invoices/{id} ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_invoice_requires_auth(client: AsyncClient, db):
    inv = await _seed_invoice(db)
    resp = await client.patch(f"/api/v1/invoices/{inv.id}", json={"vendor_name": "New"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_invoice_success(client: AsyncClient, db, auth_headers):
    inv = await _seed_invoice(db)
    resp = await client.patch(
        f"/api/v1/invoices/{inv.id}",
        json={"vendor_name": "Updated Vendor"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["vendor_name"] == "Updated Vendor"


@pytest.mark.asyncio
async def test_patch_invoice_not_found_returns_404(client: AsyncClient, auth_headers):
    resp = await client.patch(
        f"/api/v1/invoices/{uuid.uuid4()}",
        json={"vendor_name": "Ghost"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── DELETE /api/v1/invoices/{id} ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_invoice_requires_auth(client: AsyncClient, db):
    inv = await _seed_invoice(db)
    resp = await client.delete(f"/api/v1/invoices/{inv.id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_invoice_success(client: AsyncClient, db, auth_headers):
    inv = await _seed_invoice(db)
    resp = await client.delete(f"/api/v1/invoices/{inv.id}", headers=auth_headers)
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/invoices/{inv.id}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_invoice_not_found_returns_404(client: AsyncClient, auth_headers):
    resp = await client.delete(f"/api/v1/invoices/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
```

---

### 2.4 Transaction Route Tests

**File:** `tests/unit/api/test_transactions.py`

```python
import uuid
import pytest
from datetime import date
from httpx import AsyncClient
from app.db.models.document import Document
from app.db.models.transaction import Transaction


async def _seed_txn(db) -> Transaction:
    doc = Document(
        filename="txn_api.csv", original_name="txn_api.csv", file_type="csv_statement",
        mime_type="text/csv", file_size=200, file_path="/tmp/txn_api.csv",
        checksum=f"txn_api_{uuid.uuid4().hex}", status="done",
    )
    db.add(doc)
    await db.flush()
    txn = Transaction(
        document_id=doc.id, transaction_date=date(2024, 4, 10),
        description="Test Txn", amount=250, currency="USD",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


# ── GET /api/v1/transactions ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_transactions_returns_200(client: AsyncClient):
    resp = await client.get("/api/v1/transactions")
    assert resp.status_code == 200
    assert "items" in resp.json()


@pytest.mark.asyncio
async def test_list_transactions_date_filter(client: AsyncClient, db):
    await _seed_txn(db)
    resp = await client.get("/api/v1/transactions?date_from=2024-01-01&date_to=2024-12-31")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_transactions_amount_range(client: AsyncClient, db):
    await _seed_txn(db)
    resp = await client.get("/api/v1/transactions?amount_min=100&amount_max=500")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_transactions_currency_filter(client: AsyncClient, db):
    await _seed_txn(db)
    resp = await client.get("/api/v1/transactions?currency=USD")
    assert resp.status_code == 200
    assert all(t["currency"] == "USD" for t in resp.json()["items"])


@pytest.mark.asyncio
async def test_list_transactions_invalid_sort_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/transactions?sort_by=garbage")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_transactions_empty_result(client: AsyncClient):
    resp = await client.get("/api/v1/transactions?currency=XYZ")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ── GET /api/v1/transactions/{id} ────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_transaction_success(client: AsyncClient, db):
    txn = await _seed_txn(db)
    resp = await client.get(f"/api/v1/transactions/{txn.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(txn.id)


@pytest.mark.asyncio
async def test_get_transaction_not_found_returns_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/transactions/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_transaction_invalid_uuid_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/transactions/bad-id")
    assert resp.status_code == 422


# ── PATCH /api/v1/transactions/{id} ─────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_transaction_requires_auth(client: AsyncClient, db):
    txn = await _seed_txn(db)
    resp = await client.patch(f"/api/v1/transactions/{txn.id}", json={"description": "X"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_transaction_success(client: AsyncClient, db, auth_headers):
    txn = await _seed_txn(db)
    resp = await client.patch(
        f"/api/v1/transactions/{txn.id}",
        json={"description": "Updated"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated"


@pytest.mark.asyncio
async def test_patch_transaction_not_found_returns_404(client: AsyncClient, auth_headers):
    resp = await client.patch(
        f"/api/v1/transactions/{uuid.uuid4()}",
        json={"description": "Ghost"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── DELETE /api/v1/transactions/{id} ─────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_transaction_requires_auth(client: AsyncClient, db):
    txn = await _seed_txn(db)
    resp = await client.delete(f"/api/v1/transactions/{txn.id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_transaction_success(client: AsyncClient, db, auth_headers):
    txn = await _seed_txn(db)
    resp = await client.delete(f"/api/v1/transactions/{txn.id}", headers=auth_headers)
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/transactions/{txn.id}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_transaction_not_found_returns_404(client: AsyncClient, auth_headers):
    resp = await client.delete(f"/api/v1/transactions/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
```

---

## Phase 3 — Integration Tests (End-to-End)

**Priority: P2**
**Target coverage after phase:** `app/worker/tasks.py` ≥ 70%, overall project ≥ 75%

Integration tests live in `tests/integration/`. They use a real Postgres DB (same as the `test` job in CI) and execute the full request → task → DB write pipeline.

### How to Handle Celery

**Option A — `CELERY_TASK_ALWAYS_EAGER` (recommended for CI)**

Set this in the integration conftest so Celery tasks execute inline in the calling thread (no broker needed):

```python
# tests/integration/conftest.py
import pytest
from app.worker.celery_app import celery_app

@pytest.fixture(autouse=True, scope="session")
def eager_celery():
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    yield
    celery_app.conf.update(task_always_eager=False)
```

**Option B — Mock the task at the route layer** (faster, less realistic)

Replace `parse_document_task.delay` with a direct synchronous call to `_parse_document` using `asyncio.run`. Good for tests that just need the DB state after parsing.

**Option C — Real Celery worker + Redis** (use only in a dedicated slow-test suite)

Spin up a worker with `celery -A app.worker.celery_app worker --loglevel=info` before the test run. Use polling or `celery.result.AsyncResult` to wait. This is appropriate for a nightly CI job, not every PR.

**For this plan: use Option A in `tests/integration/`.**

### Task Checklist

- [ ] `tests/integration/__init__.py` — create empty file
- [ ] `tests/integration/conftest.py` — eager Celery + inherit root conftest
- [ ] `tests/integration/test_csv_upload_flow.py` — new file
- [ ] `tests/integration/test_pdf_upload_flow.py` — new file
- [ ] `tests/integration/test_duplicate_upload.py` — new file
- [ ] `tests/integration/test_failed_parse_flow.py` — new file
- [ ] `tests/integration/test_delete_cascade.py` — new file
- [ ] `tests/integration/test_auth_flow.py` — new file

---

### 3.1 Integration conftest

**File:** `tests/integration/conftest.py`

```python
import pytest
from app.worker.celery_app import celery_app


@pytest.fixture(autouse=True, scope="session")
def eager_celery():
    """Run Celery tasks synchronously so integration tests don't need a broker."""
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    yield
    celery_app.conf.update(task_always_eager=False, task_eager_propagates=False)
```

---

### 3.2 Full CSV Upload Flow

**File:** `tests/integration/test_csv_upload_flow.py`

```python
"""Full flow: upload CSV → task runs eagerly → transactions visible in DB."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.db.models.document import Document
from app.db.models.transaction import Transaction


CSV_BYTES = (
    b"date,description,amount,currency\n"
    b"2024-01-05,Salary,5000.00,USD\n"
    b"2024-01-10,Rent,-1500.00,USD\n"
    b"2024-01-15,Groceries,-87.50,USD\n"
)


@pytest.mark.asyncio
async def test_csv_upload_creates_transactions(client: AsyncClient, db, auth_headers):
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("bank.csv", CSV_BYTES, "text/csv"))],
        headers=auth_headers,
    )
    assert resp.status_code == 200
    doc_id = resp.json()["results"][0]["document"]["id"]

    # With CELERY_TASK_ALWAYS_EAGER the task has already run; re-fetch from DB
    await db.refresh(await db.get(Document, doc_id))
    doc = await db.get(Document, doc_id)
    assert doc.status == "done"

    txns = list(await db.scalars(select(Transaction).where(Transaction.document_id == doc.id)))
    assert len(txns) == 3
    descriptions = {t.description for t in txns}
    assert "Salary" in descriptions
    assert "Rent" in descriptions
    assert "Groceries" in descriptions


@pytest.mark.asyncio
async def test_csv_upload_then_list_transactions(client: AsyncClient, db, auth_headers):
    await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("bank2.csv", CSV_BYTES, "text/csv"))],
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/transactions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 3
```

---

### 3.3 Full PDF Upload Flow

**File:** `tests/integration/test_pdf_upload_flow.py`

```python
"""Full flow: upload PDF → task runs → invoice + line items visible in DB."""
import io
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy import select
from app.db.models.document import Document
from app.db.models.invoice import Invoice
from app.db.models.line_item import LineItem


FAKE_PDF_TEXT = (
    "ACME Corp Inc\n"
    "Invoice Date: 2024-05-01\n"
    "Invoice #: INV-001\n"
    "Consulting Services  800.00\n"
    "Software Licence  200.00\n"
    "Total: $1,000.00\n"
    "Tax: $100.00\n"
)


@pytest.fixture
def mock_pdfplumber():
    mock_page = MagicMock()
    mock_page.extract_text.return_value = FAKE_PDF_TEXT
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    with patch("pdfplumber.open", return_value=mock_pdf):
        yield


@pytest.mark.asyncio
async def test_pdf_upload_creates_invoice_and_line_items(
    client: AsyncClient, db, auth_headers, mock_pdfplumber
):
    pdf_bytes = b"%PDF-1.4 fake"
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("invoice.pdf", pdf_bytes, "application/pdf"))],
        headers=auth_headers,
    )
    assert resp.status_code == 200
    doc_id = resp.json()["results"][0]["document"]["id"]

    doc = await db.get(Document, doc_id)
    assert doc.status == "done"

    invoices = list(await db.scalars(select(Invoice).where(Invoice.document_id == doc.id)))
    assert len(invoices) == 1
    inv = invoices[0]
    assert inv.invoice_number == "INV-001"
    assert inv.total_amount == Decimal("1000.00")

    line_items = list(await db.scalars(select(LineItem).where(LineItem.invoice_id == inv.id)))
    assert len(line_items) == 2
```

---

### 3.4 Duplicate Upload Detection

**File:** `tests/integration/test_duplicate_upload.py`

```python
import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from app.db.models.document import Document

CSV = b"date,description,amount\n2024-06-01,DupCheck,77.00\n"


@pytest.mark.asyncio
async def test_duplicate_upload_returns_existing_document(client: AsyncClient, db, auth_headers):
    resp1 = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("dup.csv", CSV, "text/csv"))],
        headers=auth_headers,
    )
    id1 = resp1.json()["results"][0]["document"]["id"]

    resp2 = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("dup_renamed.csv", CSV, "text/csv"))],
        headers=auth_headers,
    )
    id2 = resp2.json()["results"][0]["document"]["id"]

    assert id1 == id2
    assert resp2.json()["duplicates"] == 1
    assert resp2.json()["created"] == 0

    # Only one row in DB
    count = await db.scalar(select(func.count()).select_from(Document).where(Document.id == id1))
    assert count == 1
```

---

### 3.5 Failed Parse Flow

**File:** `tests/integration/test_failed_parse_flow.py`

```python
"""Upload a corrupted file; after task runs, document.status should be 'failed'."""
import pytest
from httpx import AsyncClient
from app.db.models.document import Document


@pytest.mark.asyncio
async def test_corrupted_pdf_sets_status_failed(client: AsyncClient, db, auth_headers):
    corrupt_bytes = b"this is not a PDF at all"
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("corrupt.pdf", corrupt_bytes, "application/pdf"))],
        headers=auth_headers,
    )
    assert resp.status_code == 200
    doc_id = resp.json()["results"][0]["document"]["id"]

    # Task ran eagerly; document should now be failed
    doc = await db.get(Document, doc_id)
    assert doc.status == "failed"
    assert doc.error_message is not None
    assert len(doc.error_message) > 0


@pytest.mark.asyncio
async def test_failed_document_visible_via_get_endpoint(client: AsyncClient, db, auth_headers):
    corrupt_bytes = b"garbage bytes 1234"
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("garbage.pdf", corrupt_bytes, "application/pdf"))],
        headers=auth_headers,
    )
    doc_id = resp.json()["results"][0]["document"]["id"]
    get_resp = await client.get(f"/api/v1/documents/{doc_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "failed"
```

---

### 3.6 Delete Cascade

**File:** `tests/integration/test_delete_cascade.py`

```python
"""Delete a document; verify all child invoices, line items, and transactions are gone."""
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.db.models.document import Document
from app.db.models.invoice import Invoice
from app.db.models.transaction import Transaction
from app.db.models.line_item import LineItem


@pytest.mark.asyncio
async def test_delete_document_cascades_to_transactions(client: AsyncClient, db, auth_headers):
    csv_bytes = b"date,description,amount\n2024-07-01,Cascade,100\n"
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("cascade.csv", csv_bytes, "text/csv"))],
        headers=auth_headers,
    )
    doc_id = resp.json()["results"][0]["document"]["id"]

    # Verify transactions were created
    txns_before = list(await db.scalars(select(Transaction).where(Transaction.document_id == doc_id)))
    assert len(txns_before) >= 1

    del_resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    txns_after = list(await db.scalars(select(Transaction).where(Transaction.document_id == doc_id)))
    assert txns_after == []


@pytest.mark.asyncio
async def test_delete_document_cascades_to_invoices_and_line_items(
    client: AsyncClient, db, auth_headers
):
    from unittest.mock import patch, MagicMock

    fake_text = (
        "ACME Corp Inc\nInvoice Date: 2024-08-01\nInvoice #: INV-999\n"
        "Widget  50.00\nTotal: $50.00\n"
    )
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fake_text
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        resp = await client.post(
            "/api/v1/documents/upload",
            files=[("files", ("cascade_inv.pdf", b"%PDF-fake", "application/pdf"))],
            headers=auth_headers,
        )
    doc_id = resp.json()["results"][0]["document"]["id"]

    invoices_before = list(await db.scalars(select(Invoice).where(Invoice.document_id == doc_id)))
    assert len(invoices_before) == 1
    inv_id = invoices_before[0].id

    line_items_before = list(await db.scalars(select(LineItem).where(LineItem.invoice_id == inv_id)))
    assert len(line_items_before) >= 1

    del_resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    assert (await db.scalars(select(Invoice).where(Invoice.document_id == doc_id))).first() is None
    assert (await db.scalars(select(LineItem).where(LineItem.invoice_id == inv_id))).first() is None
```

---

### 3.7 Auth Flow End-to-End

**File:** `tests/integration/test_auth_flow.py`

```python
import pytest
from datetime import datetime, timedelta
from jose import jwt
from httpx import AsyncClient
from app.core.config import settings


@pytest.mark.asyncio
async def test_register_login_and_use_token(client: AsyncClient):
    # Register
    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "flow@example.com", "password": "securepass"},
    )
    assert reg_resp.status_code == 201

    # Login
    token_resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "flow@example.com", "password": "securepass"},
    )
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]

    # Use token to access a protected endpoint
    csv_bytes = b"date,description,amount\n2024-09-01,Auth Flow,1\n"
    upload_resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("authflow.csv", csv_bytes, "text/csv"))],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upload_resp.status_code == 200


@pytest.mark.asyncio
async def test_expired_token_rejected_on_protected_endpoint(client: AsyncClient):
    past = datetime.utcnow() - timedelta(seconds=10)
    expired = jwt.encode(
        {"sub": "flow@example.com", "exp": past},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    csv_bytes = b"date,description,amount\n2024-09-02,Exp,1\n"
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("expired.csv", csv_bytes, "text/csv"))],
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_malformed_token_rejected(client: AsyncClient):
    csv_bytes = b"date,description,amount\n2024-09-03,Bad,1\n"
    resp = await client.post(
        "/api/v1/documents/upload",
        files=[("files", ("bad.csv", csv_bytes, "text/csv"))],
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_conflict_then_login_still_works(client: AsyncClient):
    payload = {"email": "conflict@example.com", "password": "mypass"}
    await client.post("/api/v1/auth/register", json=payload)
    conflict_resp = await client.post("/api/v1/auth/register", json=payload)
    assert conflict_resp.status_code == 409

    # Original account still works
    token_resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "conflict@example.com", "password": "mypass"},
    )
    assert token_resp.status_code == 200
```

---

## Phase 4 — Coverage Tooling

**Priority: P2**

### Task Checklist

- [ ] Add `pytest-cov` invocation to `ci.yml`
- [ ] Add `[tool.coverage]` config to `pyproject.toml`
- [ ] Add per-module minimum thresholds (`--cov-fail-under`)
- [ ] Add HTML report generation to local dev workflow
- [ ] (Optional) Add coverage badge to README

---

### 4.1 Add pytest-cov to CI

`pytest-cov` is already declared in `pyproject.toml`'s `[project.optional-dependencies] dev` list. It just needs to be invoked.

**Edit `.github/workflows/ci.yml`** — replace the `Run tests` step:

```yaml
      - name: Run tests with coverage
        run: |
          pytest tests/ -v --tb=short \
            --cov=app \
            --cov-report=term-missing \
            --cov-report=xml:coverage.xml \
            --cov-fail-under=60

      - name: Upload coverage to Codecov
        if: always()
        uses: codecov/codecov-action@v4
        with:
          files: coverage.xml
          fail_ci_if_error: false
```

The `--cov-fail-under=60` sets a project-wide floor. Raise it after each phase.

---

### 4.2 Per-Module Minimum Thresholds

Add to `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["app"]
omit = [
    "app/scripts/*",
    "app/db/migrations/*",
]

[tool.coverage.report]
show_missing = true
skip_covered = false
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "\\.\\.\\.",
]

[tool.coverage.paths]
source = ["app"]
```

Enforce per-module minimums using a custom `conftest.py` check, or via separate `--cov-fail-under` calls per subdirectory in CI:

```yaml
      - name: Enforce per-module coverage floors
        run: |
          # Parsers: target 90%
          pytest tests/unit/parsers/ --cov=app/parsers --cov-fail-under=90 -q
          # Services: target 80%
          pytest tests/unit/services/ --cov=app/services --cov-fail-under=80 -q
          # Security: target 95%
          pytest tests/unit/test_security.py --cov=app/core/security --cov-fail-under=95 -q
          # API routes: target 80%
          pytest tests/unit/api/ --cov=app/api --cov-fail-under=80 -q
```

**Suggested per-module targets by phase:**

| Module | After Phase 1 | After Phase 2 | After Phase 3 |
|--------|---------------|---------------|---------------|
| `app/parsers/normalizers.py` | 95% | 95% | 95% |
| `app/parsers/csv_statement.py` | 90% | 90% | 90% |
| `app/parsers/pdf_invoice.py` | 70% | 70% | 75% |
| `app/parsers/registry.py` | 95% | 95% | 95% |
| `app/services/document_service.py` | 80% | 80% | 90% |
| `app/services/invoice_service.py` | 85% | 85% | 90% |
| `app/services/transaction_service.py` | 85% | 85% | 90% |
| `app/storage/local.py` | 90% | 90% | 90% |
| `app/core/security.py` | 95% | 95% | 95% |
| `app/api/v1/auth.py` | 30% | 90% | 95% |
| `app/api/v1/documents.py` | 10% | 85% | 90% |
| `app/api/v1/invoices.py` | 0% | 85% | 90% |
| `app/api/v1/transactions.py` | 0% | 85% | 90% |
| `app/api/deps.py` | 40% | 90% | 95% |
| `app/worker/tasks.py` | 0% | 0% | 70% |
| **Project total** | **~55%** | **~75%** | **~85%** |

---

### 4.3 HTML Coverage Reports Locally

Run the full suite locally with an HTML report:

```bash
pytest tests/ \
  --cov=app \
  --cov-report=html:htmlcov \
  --cov-report=term-missing \
  -v

open htmlcov/index.html   # macOS; or xdg-open on Linux
```

For a fast unit-only run during development:

```bash
pytest tests/unit/ \
  --cov=app \
  --cov-report=term-missing \
  -q
```

Add a `Makefile` target for convenience:

```makefile
.PHONY: test cov

test:
	pytest tests/ -v --tb=short

cov:
	pytest tests/ --cov=app --cov-report=html:htmlcov --cov-report=term-missing -q
	@echo "Report: htmlcov/index.html"
```

---

### 4.4 Coverage Badge (Optional)

**Option A — Codecov badge** (requires the Codecov action from §4.1):

Add to `README.md`:
```markdown
[![codecov](https://codecov.io/gh/<org>/lincoln/branch/main/graph/badge.svg)](https://codecov.io/gh/<org>/lincoln)
```

**Option B — genbadge (local/self-hosted)**

```bash
pip install genbadge[coverage]
pytest tests/ --cov=app --cov-report=xml:coverage.xml -q
genbadge coverage -i coverage.xml -o docs/coverage-badge.svg
```

---

## Summary: Execution Order and Dependencies

```
Phase 1 (P1, week 1-2)
  └── All unit gaps closed first; no external dependencies
  └── Run: pytest tests/unit/ --cov=app --cov-fail-under=55

Phase 2 (P1, week 2-3)
  └── Depends on: Phase 1 (auth fixtures need security.py tests to be correct)
  └── Run: pytest tests/unit/ --cov=app --cov-fail-under=75

Phase 4 tooling (P2, alongside Phase 2)
  └── pyproject.toml coverage config + CI yml changes
  └── Does not block Phase 2 tests from running

Phase 3 (P2, week 3-4)
  └── Depends on: Phase 1 + 2 complete, CI green
  └── Requires: Postgres available in CI (already configured)
  └── Requires: eager Celery conftest in tests/integration/
  └── Run: pytest tests/ --cov=app --cov-fail-under=80
```

**New files to create (summary):**

| File | Phase |
|------|-------|
| `tests/unit/parsers/test_registry.py` | 1 |
| `tests/unit/test_security.py` | 1 |
| `tests/unit/api/__init__.py` | 2 |
| `tests/unit/api/conftest.py` | 2 |
| `tests/unit/api/test_auth.py` | 2 |
| `tests/unit/api/test_documents.py` | 2 |
| `tests/unit/api/test_invoices.py` | 2 |
| `tests/unit/api/test_transactions.py` | 2 |
| `tests/integration/__init__.py` | 3 |
| `tests/integration/conftest.py` | 3 |
| `tests/integration/test_csv_upload_flow.py` | 3 |
| `tests/integration/test_pdf_upload_flow.py` | 3 |
| `tests/integration/test_duplicate_upload.py` | 3 |
| `tests/integration/test_failed_parse_flow.py` | 3 |
| `tests/integration/test_delete_cascade.py` | 3 |
| `tests/integration/test_auth_flow.py` | 3 |

**Existing files to extend:**

| File | Phase |
|------|-------|
| `tests/unit/parsers/test_normalizers.py` | 1 |
| `tests/unit/parsers/test_csv_statement_parser.py` | 1 |
| `tests/unit/parsers/test_pdf_invoice_parser.py` | 1 |
| `tests/unit/test_models.py` | 1 |
| `tests/unit/test_storage.py` | 1 |
| `tests/unit/services/test_document_service.py` | 1 |
| `tests/unit/services/test_invoice_service.py` | 1 |
| `tests/unit/services/test_transaction_service.py` | 1 |
| `pyproject.toml` | 4 |
| `.github/workflows/ci.yml` | 4 |
