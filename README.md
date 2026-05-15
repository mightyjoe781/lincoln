# Lincoln — Financial Document Parser

A production-grade FastAPI backend with a built-in web UI for uploading, parsing, and querying PDF invoices and CSV bank statements. Features JWT authentication, background processing via Celery, full-text search, Prometheus metrics, and a one-click Render deployment.

---

## Quick Start

### Requirements
- Docker + Docker Compose (recommended), or Python 3.11+ with PostgreSQL 16 and Redis

### With Docker

```bash
cp .env.example .env
# Edit .env — set JWT_SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD at minimum
docker compose up --build
```

| Service | URL |
|---|---|
| Web UI | http://localhost:8000/ |
| Swagger / OpenAPI | http://localhost:8000/docs |
| Prometheus metrics | http://localhost:8000/metrics |

On first boot the container runs:
1. `alembic upgrade head` — applies all migrations
2. `python -m app.scripts.seed` — creates the admin user if `ADMIN_EMAIL` / `ADMIN_PASSWORD` are set
3. `uvicorn app.main:app` — starts the API

### Local Development

```bash
pip install -e ".[dev]"

# Start PostgreSQL and Redis
docker run -d --name pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=lincoln -p 5432:5432 postgres:16-alpine
docker run -d --name redis -p 6379:6379 redis:7-alpine

cp .env.example .env  # edit as needed

alembic upgrade head
python -m app.scripts.seed   # optional — creates ADMIN_EMAIL user
uvicorn app.main:app --reload

# In a second terminal — start the Celery worker
celery -A app.worker.celery_app worker --loglevel=info
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...@localhost:5432/lincoln` | PostgreSQL async connection string |
| `UPLOAD_DIR` | `/tmp/lincoln_uploads` | Directory for uploaded files |
| `MAX_UPLOAD_SIZE_BYTES` | `20971520` | Max upload size (default 20 MB) |
| `ALLOWED_MIME_TYPES` | `application/pdf,text/csv,...` | Comma-separated accepted MIME types |
| `ENVIRONMENT` | `development` | Runtime environment label |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis broker URL for Celery |
| `JWT_SECRET_KEY` | `change-me-in-production` | Secret for signing JWT tokens — **must be changed** |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token TTL in minutes |
| `ADMIN_EMAIL` | *(empty)* | Default admin user email — created on first boot if set |
| `ADMIN_PASSWORD` | *(empty)* | Default admin user password |

> **Note:** `postgresql://` URLs (e.g. from Render) are automatically rewritten to `postgresql+asyncpg://` at runtime — no manual transformation needed.

---

## Authentication

All write operations (`POST`, `PATCH`, `DELETE`) require a Bearer token. Read operations (`GET`) are public.

### Create an account

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "yourpassword"}'
```

### Get a token

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=you@example.com&password=yourpassword"
# → {"access_token": "eyJ...", "token_type": "bearer"}
```

### Use the token

```bash
curl -X DELETE http://localhost:8000/api/v1/documents/<id> \
  -H "Authorization: Bearer eyJ..."
```

The web UI handles registration, login, and token storage automatically via the login modal.

---

## API Endpoints

### Auth
| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | — | Register a new user |
| `POST` | `/api/v1/auth/token` | — | Login, returns JWT |

### Documents
| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/documents/upload` | Required | Upload PDF or CSV — parsing runs in background |
| `GET` | `/api/v1/documents` | — | List documents (paginated) |
| `GET` | `/api/v1/documents/{id}` | — | Get document metadata and status |
| `DELETE` | `/api/v1/documents/{id}` | Required | Delete document and all parsed data |

### Invoices
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/invoices` | — | List invoices with filters |
| `GET` | `/api/v1/invoices/{id}` | — | Get invoice with line items |
| `PATCH` | `/api/v1/invoices/{id}` | Required | Update invoice fields |
| `DELETE` | `/api/v1/invoices/{id}` | Required | Delete invoice |

### Transactions
| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/transactions` | — | List transactions with filters |
| `GET` | `/api/v1/transactions/{id}` | — | Get transaction |
| `PATCH` | `/api/v1/transactions/{id}` | Required | Update transaction fields |
| `DELETE` | `/api/v1/transactions/{id}` | Required | Delete transaction |

### Filter Parameters

**Invoices:** `vendor_name` (partial), `date_from`, `date_to`, `amount_min`, `amount_max`, `currency`, `q` (full-text), `page`, `page_size`, `sort_by` (date|amount|vendor), `sort_order` (asc|desc)

**Transactions:** `date_from`, `date_to`, `amount_min`, `amount_max`, `currency`, `q` (full-text on description), `page`, `page_size`, `sort_by` (date|amount), `sort_order` (asc|desc)

---

## Document Processing

Upload returns immediately with `status: "pending"`. A Celery worker picks up the task and transitions the document through:

```
pending → processing → done
                    ↘ failed  (error_message populated)
```

Poll `GET /api/v1/documents/{id}` to check status. The web UI polls automatically every 2 seconds.

---

## Database Schema

| Table | Description |
|---|---|
| `documents` | Upload metadata, processing status, SHA-256 checksum (deduplication), file path |
| `invoices` | Extracted invoice data — vendor, dates, amounts, currency, raw text, tsvector |
| `line_items` | Individual line items belonging to an invoice |
| `transactions` | Bank statement rows — date, description, amount, debit/credit, balance |
| `users` | Registered users — email, bcrypt-hashed password |

Migrations live in `alembic/versions/` and run automatically on container start.

---

## Running Tests

```bash
# Start a test database
docker run -d --name pg-test \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=lincoln_test -p 5433:5432 postgres:16-alpine

DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/lincoln_test \
  alembic upgrade head

pytest -v
```

The CI pipeline (`.github/workflows/ci.yml`) runs lint and tests automatically on every push and pull request.

---

## Web UI

A minimal single-page app served directly from the FastAPI app at `/`. No build step — plain HTML + vanilla JS + Tailwind CSS (CDN).

**Authentication:** A login/register modal appears on first load. The JWT is stored in `localStorage` and sent automatically on write requests. Session expiry shows the modal again.

| Tab | Features |
|---|---|
| **Upload** | Drag-and-drop or file picker; real-time status badge with 2 s polling; delete documents |
| **Invoices** | Vendor / date / currency filters with 400 ms debounce; slide-in detail panel with line items |
| **Transactions** | Full-text search, date / currency filters; debit/credit colour coding |

Files live in `ui/` and are mounted via FastAPI `StaticFiles`.

---

## Architecture

```
app/
├── api/v1/          # FastAPI route handlers (documents, invoices, transactions, auth)
├── core/            # Config, structured logging (structlog), exceptions, rate limiter, middleware
├── db/models/       # SQLAlchemy ORM models (Document, Invoice, LineItem, Transaction, User)
├── parsers/         # PDF (pdfplumber) + CSV parsers, normalizers, parser registry
├── schemas/         # Pydantic v2 request/response models
├── scripts/         # seed.py — default admin user creation
├── services/        # Business logic (DocumentService, InvoiceService, TransactionService)
├── storage/         # File storage abstraction (LocalFileStorage, read/save/delete)
└── worker/          # Celery app and parse_document_task
ui/
├── index.html       # Single-page tab layout + login modal
├── app.js           # Auth flow, upload, polling, list/filter, detail panel
└── style.css        # Tailwind overrides (drag-over, skeleton, panel slide)
alembic/versions/
├── 0001_initial_schema.py      # documents, invoices, line_items, transactions
├── 0002_fulltext_search.py     # tsvector columns + GIN indexes + triggers
└── 0003_users_table.py         # users table
```

---

## Observability

- **`GET /metrics`** — Prometheus metrics (request count, latency histograms, error rates) via `prometheus-fastapi-instrumentator`
- **Structured logging** — every request emits a JSON log line with `request_id`, `method`, `path`, `level` via `structlog`
- **`X-Request-ID` header** — each response carries the request ID for log correlation

To spin up a local Prometheus + Grafana stack:

```bash
docker compose --profile monitoring up
```

Prometheus UI at http://localhost:9090, Grafana at http://localhost:3000 (admin / admin).

---

## Cloud Deployment

### Render (one-click)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

See [`deployment/render.md`](deployment/render.md) for full instructions. The `render.yaml` Blueprint provisions the API, PostgreSQL, and Redis in one step. `JWT_SECRET_KEY` is auto-generated on first deploy.

### VPS / Self-hosted

```bash
# On the VPS
git clone <repo> && cd lincoln
cp .env.example .env  # fill in secrets
docker compose up -d --build
```

Point your existing Prometheus instance at `http://<host>:8000/metrics` to scrape metrics into your existing Grafana dashboards.

