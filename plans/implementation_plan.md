# Implementation Plan — Invoice & Bank Statement Parsing API

## Overview

Build a production-grade FastAPI backend that ingests PDF invoices and CSV bank
statements, extracts structured financial data, persists it in PostgreSQL, and
exposes a full CRUD + search API.

**Approach:** Task-Driven Development (TDD) — break work into discrete phases
and tasks, implement each task to completion before moving to the next.

---

## Tech Stack

| Layer              | Choice                              |
|--------------------|-------------------------------------|
| API                | FastAPI + Uvicorn                   |
| ORM                | SQLAlchemy 2.x (async)              |
| DB                 | PostgreSQL 16                       |
| Migrations         | Alembic                             |
| PDF parsing        | pdfplumber (primary), PyMuPDF (fallback) |
| CSV parsing        | pandas / csv stdlib                 |
| Validation         | Pydantic v2                         |
| File storage       | Local filesystem (S3-ready adapter) |
| Testing            | pytest + pytest-asyncio + httpx     |
| Containerization   | Docker + Docker Compose             |
| Auth (bonus)       | python-jose + passlib (JWT)         |
| Background jobs    | Celery + Redis (bonus)              |

---

## Project Structure

```
lincoln/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py              # FastAPI dependency injection
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py        # aggregates all v1 routes
│   │       ├── documents.py     # upload / retrieve / delete endpoints
│   │       ├── invoices.py      # invoice-specific CRUD + search
│   │       └── transactions.py  # bank-statement CRUD + search
│   ├── core/
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── logging.py           # structlog / stdlib setup
│   │   └── security.py          # JWT helpers (bonus)
│   ├── db/
│   │   ├── base.py              # declarative Base
│   │   ├── session.py           # async engine + get_db()
│   │   └── models/
│   │       ├── document.py
│   │       ├── invoice.py
│   │       ├── line_item.py
│   │       └── transaction.py
│   ├── parsers/
│   │   ├── base.py              # AbstractParser protocol
│   │   ├── pdf_invoice.py
│   │   ├── csv_statement.py
│   │   ├── normalizers.py       # date / currency / amount helpers
│   │   └── registry.py          # maps mime-type → parser
│   ├── schemas/
│   │   ├── document.py
│   │   ├── invoice.py
│   │   ├── line_item.py
│   │   └── transaction.py
│   ├── services/
│   │   ├── document_service.py
│   │   ├── invoice_service.py
│   │   └── transaction_service.py
│   ├── storage/
│   │   ├── base.py              # AbstractStorage protocol
│   │   └── local.py             # LocalFileStorage implementation
│   └── main.py
├── alembic/
│   ├── env.py
│   └── versions/
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── parsers/
│   │   │   ├── test_pdf_invoice_parser.py
│   │   │   ├── test_csv_statement_parser.py
│   │   │   └── test_normalizers.py
│   │   └── services/
│   │       ├── test_document_service.py
│   │       ├── test_invoice_service.py
│   │       └── test_transaction_service.py
│   ├── integration/
│   │   ├── test_documents_api.py
│   │   ├── test_invoices_api.py
│   │   └── test_transactions_api.py
│   └── fixtures/
│       ├── sample_invoice.pdf
│       ├── sample_invoice_partial.pdf   # missing fields
│       ├── sample_statement.csv
│       └── sample_statement_messy.csv   # bad dates, mixed currencies
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── alembic.ini
├── pyproject.toml
└── README.md
```

---

## Database Schema

### `documents` (upload metadata + processing status)

```sql
id            UUID        PK default gen_random_uuid()
filename      TEXT        NOT NULL
original_name TEXT        NOT NULL
file_type     TEXT        NOT NULL   -- 'pdf_invoice' | 'csv_statement'
mime_type     TEXT        NOT NULL
file_size     INTEGER     NOT NULL
file_path     TEXT        NOT NULL   -- storage location
checksum      TEXT        NOT NULL   -- SHA-256; unique for dedup
status        TEXT        NOT NULL   -- 'pending' | 'processing' | 'done' | 'failed'
error_message TEXT
uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
processed_at  TIMESTAMPTZ
```

### `invoices`

```sql
id            UUID        PK
document_id   UUID        FK → documents.id ON DELETE CASCADE
vendor_name   TEXT
invoice_date  DATE
due_date      DATE
invoice_number TEXT
total_amount  NUMERIC(15,4)
currency      TEXT        -- ISO 4217 e.g. 'USD'
tax_amount    NUMERIC(15,4)
raw_text      TEXT        -- full extracted text for full-text search
created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
```

### `line_items`

```sql
id            UUID        PK
invoice_id    UUID        FK → invoices.id ON DELETE CASCADE
description   TEXT
quantity      NUMERIC(10,4)
unit_price    NUMERIC(15,4)
total         NUMERIC(15,4)
currency      TEXT
```

### `transactions`

```sql
id             UUID        PK
document_id    UUID        FK → documents.id ON DELETE CASCADE
transaction_date DATE
description    TEXT
amount         NUMERIC(15,4)
currency       TEXT
debit_credit   TEXT        -- 'debit' | 'credit'
balance        NUMERIC(15,4)
reference      TEXT
created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
```

**Indexes:**
- `documents(checksum)` UNIQUE — deduplication
- `invoices(vendor_name)` — vendor filter
- `invoices(invoice_date)` — date range filter
- `transactions(transaction_date)` — date range filter
- `invoices(currency)`, `transactions(currency)`

---

## API Endpoints

### Documents

| Method | Path                        | Description                        |
|--------|-----------------------------|------------------------------------|
| POST   | `/api/v1/documents/upload`  | Upload PDF or CSV, trigger parsing |
| GET    | `/api/v1/documents`         | List all documents (paginated)     |
| GET    | `/api/v1/documents/{id}`    | Get document metadata              |
| DELETE | `/api/v1/documents/{id}`    | Delete document and all parsed data|

### Invoices

| Method | Path                        | Description                        |
|--------|-----------------------------|------------------------------------|
| GET    | `/api/v1/invoices`          | List invoices with filters         |
| GET    | `/api/v1/invoices/{id}`     | Get invoice + line items           |
| PATCH  | `/api/v1/invoices/{id}`     | Update invoice metadata            |
| DELETE | `/api/v1/invoices/{id}`     | Delete invoice                     |

### Transactions

| Method | Path                         | Description                       |
|--------|------------------------------|-----------------------------------|
| GET    | `/api/v1/transactions`       | List transactions with filters    |
| GET    | `/api/v1/transactions/{id}`  | Get single transaction            |
| PATCH  | `/api/v1/transactions/{id}`  | Update transaction                |
| DELETE | `/api/v1/transactions/{id}`  | Delete transaction                |

### Filter Query Params (invoices + transactions)

```
vendor_name=     (invoices only, partial match)
date_from=       ISO date
date_to=         ISO date
amount_min=
amount_max=
currency=        ISO 4217
doc_type=        pdf_invoice | csv_statement
status=          pending | processing | done | failed
page=            default 1
page_size=       default 20, max 100
sort_by=         date | amount | vendor
sort_order=      asc | desc
q=               full-text search on raw_text / description
```

---

## TDD Implementation Phases

Each phase follows the Red → Green → Refactor cycle.

---

### Phase 0 — Project Bootstrap (no tests yet)

- [ ] `pyproject.toml` with all dependencies
- [ ] `app/core/config.py` — `Settings` via `pydantic-settings`, reads `.env`
- [ ] `app/db/session.py` — async engine, `get_db` dependency
- [ ] `app/main.py` — bare FastAPI app, health endpoint `GET /health`
- [ ] `docker-compose.yml` — postgres + app services
- [ ] `alembic/` initialized, `env.py` wired to async engine

**Deliverable:** `docker compose up` serves `GET /health → 200`.

---

### Phase 1 — Database Models + Migrations

**TDD targets:** model instantiation, relationship integrity, checksum uniqueness.

#### Tests to write first

```python
# tests/unit/test_models.py
def test_document_model_defaults():
    doc = Document(filename="x.pdf", ...)
    assert doc.status == "pending"

def test_invoice_requires_document_id():
    with pytest.raises(IntegrityError):
        # insert invoice without document_id
        ...

def test_checksum_unique_constraint():
    # inserting two documents with same checksum should raise
    ...
```

#### Implementation steps

- [ ] `app/db/models/document.py`
- [ ] `app/db/models/invoice.py` + `app/db/models/line_item.py`
- [ ] `app/db/models/transaction.py`
- [ ] `alembic revision --autogenerate -m "initial schema"`
- [ ] `alembic upgrade head` in test `conftest.py` fixture

---

### Phase 2 — Normalizers (pure functions, easiest to TDD)

**TDD targets:** date parsing, currency normalization, amount cleaning.

#### Tests to write first

```python
# tests/unit/parsers/test_normalizers.py

@pytest.mark.parametrize("raw,expected", [
    ("15/05/2024", date(2024, 5, 15)),
    ("May 15 2024", date(2024, 5, 15)),
    ("2024-05-15", date(2024, 5, 15)),
    ("", None),
    ("not-a-date", None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected

@pytest.mark.parametrize("raw,expected", [
    ("$1,234.56", Decimal("1234.56")),
    ("USD 1234.56", Decimal("1234.56")),
    ("1.234,56 EUR", Decimal("1234.56")),
    ("", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected

@pytest.mark.parametrize("raw,expected", [
    ("$", "USD"), ("€", "EUR"), ("USD", "USD"), ("", None)
])
def test_normalize_currency(raw, expected):
    assert normalize_currency(raw) == expected
```

#### Implementation steps

- [ ] `app/parsers/normalizers.py` — `parse_date`, `parse_amount`, `normalize_currency`
- All three functions return `None` on unparseable input (never raise)

---

### Phase 3 — Parser Layer

**TDD targets:** happy path, missing fields, malformed input, unknown format.

#### 3a. PDF Invoice Parser

```python
# tests/unit/parsers/test_pdf_invoice_parser.py

def test_parse_happy_path(sample_invoice_pdf):
    result = PdfInvoiceParser().parse(sample_invoice_pdf)
    assert result.vendor_name == "Acme Corp"
    assert result.total_amount == Decimal("1500.00")
    assert result.currency == "USD"
    assert len(result.line_items) == 3

def test_parse_missing_vendor(partial_invoice_pdf):
    result = PdfInvoiceParser().parse(partial_invoice_pdf)
    assert result.vendor_name is None      # graceful, not raised
    assert result.parse_warnings           # warnings recorded

def test_parse_returns_raw_text(sample_invoice_pdf):
    result = PdfInvoiceParser().parse(sample_invoice_pdf)
    assert len(result.raw_text) > 0

def test_parse_corrupted_pdf_raises_parse_error(corrupted_bytes):
    with pytest.raises(ParseError):
        PdfInvoiceParser().parse(corrupted_bytes)
```

#### 3b. CSV Statement Parser

```python
# tests/unit/parsers/test_csv_statement_parser.py

def test_parse_standard_csv(sample_statement_csv):
    rows = CsvStatementParser().parse(sample_statement_csv)
    assert len(rows) == 10
    assert rows[0].amount == Decimal("250.00")
    assert rows[0].currency == "USD"

def test_parse_messy_csv_dates(messy_statement_csv):
    rows = CsvStatementParser().parse(messy_statement_csv)
    # all dates normalised, None for unparseable
    assert all(r.transaction_date is not None or r.parse_warnings for r in rows)

def test_parse_empty_csv_returns_empty_list():
    rows = CsvStatementParser().parse(b"date,description,amount\n")
    assert rows == []

def test_parse_missing_required_column_raises():
    with pytest.raises(ParseError):
        CsvStatementParser().parse(b"foo,bar\n1,2\n")
```

#### Implementation steps

- [ ] `app/parsers/base.py` — `AbstractParser` protocol + `ParseResult` dataclass + `ParseError`
- [ ] `app/parsers/pdf_invoice.py`
- [ ] `app/parsers/csv_statement.py`
- [ ] `app/parsers/registry.py` — `get_parser(mime_type) → AbstractParser`
- [ ] Add fixture PDFs/CSVs to `tests/fixtures/`

---

### Phase 4 — Storage Layer

**TDD targets:** save, retrieve, delete, path collision avoidance.

```python
# tests/unit/test_storage.py

def test_save_returns_deterministic_path(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    path = await storage.save(b"data", "invoice.pdf", "abc123")
    assert path.endswith("abc123.pdf")

def test_save_twice_same_checksum_does_not_duplicate(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    p1 = await storage.save(b"data", "a.pdf", "same")
    p2 = await storage.save(b"data", "b.pdf", "same")
    assert p1 == p2

async def test_delete_removes_file(tmp_path):
    ...
```

#### Implementation steps

- [ ] `app/storage/base.py` — `AbstractStorage` protocol
- [ ] `app/storage/local.py` — stores at `{base_dir}/{checksum}{ext}`

---

### Phase 5 — Service Layer

**TDD targets:** orchestration, status transitions, dedup guard, error propagation.

```python
# tests/unit/services/test_document_service.py

async def test_upload_sets_status_done_on_success(db, mock_storage, mock_parser):
    svc = DocumentService(db, mock_storage)
    doc = await svc.upload(file_bytes=b"...", filename="inv.pdf")
    assert doc.status == "done"

async def test_upload_sets_status_failed_on_parse_error(db, mock_storage, failing_parser):
    doc = await svc.upload(file_bytes=b"...", filename="bad.pdf")
    assert doc.status == "failed"
    assert doc.error_message is not None

async def test_upload_duplicate_returns_existing_document(db, mock_storage):
    doc1 = await svc.upload(b"same", "a.pdf")
    doc2 = await svc.upload(b"same", "b.pdf")
    assert doc1.id == doc2.id

async def test_delete_removes_document_and_file(db, mock_storage):
    doc = await svc.upload(b"x", "inv.pdf")
    await svc.delete(doc.id)
    assert await svc.get(doc.id) is None
```

```python
# tests/unit/services/test_invoice_service.py

async def test_list_invoices_filter_by_vendor(db, seeded_invoices):
    results = await InvoiceService(db).list(vendor_name="Acme")
    assert all("Acme" in r.vendor_name for r in results)

async def test_list_invoices_date_range(db, seeded_invoices):
    results = await InvoiceService(db).list(
        date_from=date(2024,1,1), date_to=date(2024,6,30)
    )
    assert all(date(2024,1,1) <= r.invoice_date <= date(2024,6,30) for r in results)

async def test_list_pagination(db, seeded_invoices):
    page1 = await InvoiceService(db).list(page=1, page_size=5)
    page2 = await InvoiceService(db).list(page=2, page_size=5)
    assert len(page1) == 5
    assert page1[0].id != page2[0].id
```

#### Implementation steps

- [ ] `app/services/document_service.py`
- [ ] `app/services/invoice_service.py`
- [ ] `app/services/transaction_service.py`

---

### Phase 6 — API Layer (Integration Tests)

Use `httpx.AsyncClient` with a test database. Tests hit real HTTP endpoints.

```python
# tests/integration/test_documents_api.py

async def test_upload_pdf_returns_201(client, sample_invoice_pdf):
    resp = await client.post("/api/v1/documents/upload",
                             files={"file": ("inv.pdf", sample_invoice_pdf, "application/pdf")})
    assert resp.status_code == 201
    assert resp.json()["status"] == "done"

async def test_upload_duplicate_returns_200_with_existing(client, sample_invoice_pdf):
    r1 = await client.post(...)
    r2 = await client.post(...)
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]

async def test_upload_invalid_type_returns_422(client):
    resp = await client.post("/api/v1/documents/upload",
                             files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert resp.status_code == 422

async def test_upload_oversized_file_returns_413(client, large_file):
    resp = await client.post(...)
    assert resp.status_code == 413

async def test_delete_document_returns_204(client, uploaded_doc):
    resp = await client.delete(f"/api/v1/documents/{uploaded_doc['id']}")
    assert resp.status_code == 204
```

```python
# tests/integration/test_invoices_api.py

async def test_list_invoices_empty(client):
    resp = await client.get("/api/v1/invoices")
    assert resp.status_code == 200
    assert resp.json()["items"] == []

async def test_get_invoice_includes_line_items(client, uploaded_invoice_doc):
    invoice_id = uploaded_invoice_doc["invoice_id"]
    resp = await client.get(f"/api/v1/invoices/{invoice_id}")
    assert "line_items" in resp.json()

async def test_filter_by_vendor(client, seeded_invoices):
    resp = await client.get("/api/v1/invoices?vendor_name=Acme")
    assert all("Acme" in i["vendor_name"] for i in resp.json()["items"])

async def test_patch_invoice_updates_vendor(client, uploaded_invoice_doc):
    resp = await client.patch(f"/api/v1/invoices/{...}",
                              json={"vendor_name": "New Vendor"})
    assert resp.status_code == 200
    assert resp.json()["vendor_name"] == "New Vendor"
```

#### Implementation steps

- [ ] `app/schemas/` — Pydantic request/response models
- [ ] `app/api/v1/documents.py`
- [ ] `app/api/v1/invoices.py`
- [ ] `app/api/v1/transactions.py`
- [ ] `app/api/v1/router.py`
- [ ] `app/api/deps.py` — `get_db`, `get_document_service`, etc.
- [ ] Wire into `app/main.py`

---

### Phase 7 — Error Handling + Logging

**TDD targets:** structured error responses, no stack traces leaked to client.

```python
async def test_404_on_missing_document(client):
    resp = await client.get("/api/v1/documents/nonexistent-uuid")
    assert resp.status_code == 404
    assert "detail" in resp.json()

async def test_parsing_failure_captured_in_status(client, corrupted_pdf):
    resp = await client.post("/api/v1/documents/upload", files={...})
    assert resp.status_code == 201
    assert resp.json()["status"] == "failed"
    assert resp.json()["error_message"] is not None
```

#### Implementation steps

- [ ] `app/core/logging.py` — structured JSON logging
- [ ] Global exception handler in `app/main.py`
- [ ] Custom `HTTPException` subclasses for domain errors

---

### Phase 8 — Deployment

- [ ] `Dockerfile` — multi-stage, non-root user
- [ ] `docker-compose.yml` — app + postgres + (optional) redis + celery
- [ ] `.env.example`
- [ ] `alembic upgrade head` in container entrypoint
- [ ] `README.md` — setup, run, env vars, API docs link

---

### Phase 9 — Bonus Items (if time allows)

- [ ] JWT auth — `POST /api/v1/auth/token`, protect write endpoints
- [ ] Celery worker — move parsing to background task, poll `/documents/{id}` for status
- [ ] Rate limiting — `slowapi` middleware
- [ ] Full-text search — PostgreSQL `tsvector` on `raw_text`
- [ ] CI — GitHub Actions: lint + test on PR

---

## `conftest.py` Skeleton

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.base import Base
from app.api.deps import get_db

TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/test_db"

@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DB_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()

@pytest_asyncio.fixture
async def db(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

@pytest_asyncio.fixture
async def client(db):
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Async SQLAlchemy 2.x | Matches FastAPI's async model; avoids thread-pool overhead |
| SHA-256 checksum for dedup | Deterministic; no content comparison needed at upload time |
| `status` field on documents | Decouples upload from parsing; enables async processing later |
| `None` on parse failure (not raise) | Partial data is better than no data; errors logged in `parse_warnings` |
| Parser registry by mime-type | Open/closed — add new parsers without touching upload logic |
| `raw_text` on invoices | Enables full-text search without re-parsing |
| Separate `line_items` table | Avoids JSON columns; enables amount aggregation queries |

---

## Execution Order Summary

```
Phase 0  Bootstrap + Health
Phase 1  DB Models + Migrations
Phase 2  Normalizers (pure TDD)
Phase 3  Parsers (unit-tested against fixture files)
Phase 4  Storage layer
Phase 5  Services (mock storage/parser in unit tests)
Phase 6  API integration tests (real DB, real HTTP)
Phase 7  Error handling + logging
Phase 8  Docker + deployment
Phase 9  Bonus
```
