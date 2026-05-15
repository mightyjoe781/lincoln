# Lincoln — Financial Document Parser

A production-grade FastAPI backend with a built-in web UI for uploading, parsing, and querying PDF invoices and CSV bank statements.

## Quick Start

### Requirements
- Docker + Docker Compose, or Python 3.11+ and PostgreSQL 16

### With Docker

```bash
cp .env.example .env
docker compose up --build
```

Web UI at http://localhost:8000/  
Swagger UI at http://localhost:8000/docs

### Local Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Start PostgreSQL (e.g. via Docker)
docker run -d -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=lincoln -p 5432:5432 postgres:16-alpine

# Configure environment
cp .env.example .env

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/lincoln` | PostgreSQL connection string |
| `UPLOAD_DIR` | `/tmp/lincoln_uploads` | Directory for uploaded files |
| `MAX_UPLOAD_SIZE_BYTES` | `20971520` | Max file size (20 MB) |
| `ENVIRONMENT` | `development` | Environment name |

## API Endpoints

### Documents
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/documents/upload` | Upload PDF invoice or CSV statement |
| `GET` | `/api/v1/documents` | List documents (paginated) |
| `GET` | `/api/v1/documents/{id}` | Get document metadata |
| `DELETE` | `/api/v1/documents/{id}` | Delete document and all parsed data |

### Invoices
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/invoices` | List invoices with filters |
| `GET` | `/api/v1/invoices/{id}` | Get invoice with line items |
| `PATCH` | `/api/v1/invoices/{id}` | Update invoice fields |
| `DELETE` | `/api/v1/invoices/{id}` | Delete invoice |

### Transactions
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/transactions` | List transactions with filters |
| `GET` | `/api/v1/transactions/{id}` | Get transaction |
| `PATCH` | `/api/v1/transactions/{id}` | Update transaction fields |
| `DELETE` | `/api/v1/transactions/{id}` | Delete transaction |

### Filter Parameters

**Invoices:** `vendor_name`, `date_from`, `date_to`, `amount_min`, `amount_max`, `currency`, `page`, `page_size`, `sort_by` (date|amount|vendor), `sort_order` (asc|desc)

**Transactions:** `date_from`, `date_to`, `amount_min`, `amount_max`, `currency`, `page`, `page_size`, `sort_by` (date|amount), `sort_order` (asc|desc)

## Database Schema

- **documents** — upload metadata, processing status, SHA-256 checksum for deduplication
- **invoices** — extracted invoice data (vendor, dates, amounts, currency) linked to a document
- **line_items** — individual line items belonging to an invoice
- **transactions** — bank statement rows linked to a document

## Running Tests

```bash
# Start a test database
docker run -d -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=lincoln_test -p 5432:5432 postgres:16-alpine

alembic upgrade head

pytest -v
```

## Web UI

A minimal single-page interface is served directly from the FastAPI app at `/`. No build step required — plain HTML + vanilla JS + Tailwind CSS (CDN).

| Tab | Features |
|---|---|
| **Upload** | Drag-and-drop or file picker; real-time processing status via polling; delete documents |
| **Invoices** | Filterable, paginated table; slide-in detail panel with line items |
| **Transactions** | Filterable, paginated table; debit/credit colour coding |

Files live in `ui/` and are mounted via FastAPI `StaticFiles`.

## Architecture

```
app/
├── api/v1/          # FastAPI route handlers
├── core/            # Config, logging, exceptions
├── db/models/       # SQLAlchemy ORM models
├── parsers/         # PDF + CSV parsers, normalizers
├── schemas/         # Pydantic request/response models
├── services/        # Business logic layer
└── storage/         # File storage abstraction
ui/
├── index.html       # Single-page tab layout
├── app.js           # All JS — upload, polling, list, filter, detail panel
└── style.css        # Tailwind overrides
```

## Known Limitations

- PDF parsing is regex-based and works best with text-layer PDFs (not scanned images)
- CSV parser requires at minimum: `date`, `description`, and `amount` columns (flexible aliases supported)
- File storage is local filesystem; swap `LocalFileStorage` for an S3 adapter for cloud deployments
- No authentication — add JWT middleware before exposing publicly
