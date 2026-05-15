# Optional Objectives — Lincoln API

Bonus items from the requirements. Each is independent — implement in any order.
All are self-contained additions on top of the completed core (phases 0–8).

---

## 1. Background Processing (Celery + Redis)

**Goal:** Move parsing off the upload request. `POST /upload` returns immediately with `status=pending`; a Celery worker processes the file asynchronously.

**Why it matters:** Large PDFs can take 2–5 s to parse. Blocking the HTTP worker ties up a connection slot and degrades throughput under load.

**Tasks:**
- [ ] Add `celery`, `redis` to `pyproject.toml`
- [ ] Add `redis` service to `docker-compose.yml`
- [ ] Create `app/worker/tasks.py` — `parse_document_task(document_id: str)`
- [ ] Modify `DocumentService.upload`: save file + create `Document(status="pending")`, enqueue task, return document immediately
- [ ] Worker task: load document, run parser, persist results, update status
- [ ] `GET /documents/{id}` already exposes `status` — clients poll until `done` or `failed`
- [ ] Add `celery` service to `docker-compose.yml` (same image, CMD override)

**Deliverable:** Upload returns 201 instantly; status transitions `pending → processing → done` visible via polling.

---

## 2. JWT Authentication

**Goal:** Protect all write endpoints (`POST`, `PATCH`, `DELETE`) behind Bearer token auth. Read endpoints remain public.

**Tasks:**
- [ ] Add `python-jose[cryptography]`, `passlib[bcrypt]` to `pyproject.toml`
- [ ] `app/core/security.py` — `create_access_token`, `verify_token`, password hashing
- [ ] `app/db/models/user.py` — `users` table: `id`, `email`, `hashed_password`, `created_at`
- [ ] `app/api/v1/auth.py` — `POST /api/v1/auth/register`, `POST /api/v1/auth/token`
- [ ] `app/api/deps.py` — `get_current_user` dependency (raises 401 on invalid/missing token)
- [ ] Apply `Depends(get_current_user)` to write endpoints in documents, invoices, transactions routers
- [ ] New Alembic migration for `users` table
- [ ] `.env.example`: add `JWT_SECRET_KEY`, `JWT_ALGORITHM=HS256`, `ACCESS_TOKEN_EXPIRE_MINUTES=30`

**Deliverable:** Unauthenticated `DELETE /documents/{id}` returns 401; valid Bearer token returns 204.

---

## 3. Full-Text Search

**Goal:** `GET /invoices?q=consulting` and `GET /transactions?q=amazon` search across `raw_text` / `description` using PostgreSQL `tsvector`.

**Tasks:**
- [ ] New Alembic migration: add `tsvector` column + GIN index to `invoices.raw_text` and `transactions.description`
- [ ] Add trigger (or SQLAlchemy `event.listen`) to keep `tsvector` column in sync on insert/update
- [ ] `InvoiceService.list` / `TransactionService.list`: when `q` is provided, add `WHERE search_vector @@ plainto_tsquery('english', :q)` clause
- [ ] Expose `q=` query param on both list endpoints (already scaffolded in the filter params section of the plan)

**Deliverable:** `GET /api/v1/invoices?q=web+development` returns invoices whose raw text contains those terms.

---

## 4. Rate Limiting

**Goal:** Prevent abuse of the upload endpoint. Limit to 10 uploads per IP per minute.

**Tasks:**
- [ ] Add `slowapi` to `pyproject.toml`
- [ ] Wire `slowapi` limiter into `app/main.py` (add `SlowAPIMiddleware`, register exception handler)
- [ ] Apply `@limiter.limit("10/minute")` to `POST /api/v1/documents/upload`
- [ ] Return 429 with `{"detail": "Rate limit exceeded"}` on breach

**Deliverable:** Rapid-fire upload requests from the same IP get 429 after the 10th request in a sliding minute window.

---

## 5. CI/CD Pipeline (GitHub Actions)

**Goal:** Run lint + tests on every PR; block merge if checks fail.

**Tasks:**
- [ ] `.github/workflows/ci.yml`:
  - Trigger: `push` to `main`, `pull_request`
  - Jobs: `lint` (ruff, mypy), `test` (spin up postgres service container, run `pytest`)
- [ ] Add `ruff`, `mypy` to dev dependencies in `pyproject.toml`
- [ ] `ruff.toml` or `[tool.ruff]` section in `pyproject.toml`
- [ ] Ensure `pytest` runs against a test database (use `TEST_DATABASE_URL` env var in CI)

**Deliverable:** Green badge on README; PRs blocked by failed checks.

---

## 6. Cloud Deployment (Render / AWS)

**Goal:** Publicly accessible deployment with a live URL to include in the submission.

### Option A — Render (simplest)
- [ ] `render.yaml` — web service (app) + PostgreSQL managed DB
- [ ] Set `DATABASE_URL` via Render environment secret
- [ ] `alembic upgrade head` as the pre-deploy command
- [ ] Add live URL to `README.md`

### Option B — AWS (ECS + RDS)
- [ ] ECR repository + `docker push` to ECR in CI
- [ ] ECS Fargate task definition (app container + env vars from SSM Parameter Store)
- [ ] RDS PostgreSQL instance (free-tier `db.t3.micro`)
- [ ] Application Load Balancer
- [ ] `deployment/` directory with Terraform or CloudFormation template

**Deliverable:** Live URL that accepts `POST /api/v1/documents/upload`.

---

## 7. Observability Enhancements

**Goal:** Make the running service inspectable without reading raw logs.

**Tasks:**
- [ ] Add `prometheus-fastapi-instrumentator` to `pyproject.toml`
- [ ] Mount `/metrics` endpoint exposing request count, latency histograms, error rates
- [ ] Add `structlog` for richer structured logging (request-id per request via middleware)
- [ ] `docker-compose.yml`: add Prometheus + Grafana services (optional local stack)
- [ ] Log parse duration per document (useful for profiling slow PDFs)

**Deliverable:** `GET /metrics` returns Prometheus-format metrics; request IDs visible in logs.

---

## Priority Order (recommended)

| Priority | Item                     | Effort | Impact         |
|----------|--------------------------|--------|----------------|
| 1        | Unit + integration tests | Medium | Required for bonus credit |
| 2        | JWT auth                 | Medium | Explicitly listed as bonus |
| 3        | Background processing    | High   | Explicitly listed as bonus |
| 4        | Full-text search         | Low    | Explicitly listed as bonus |
| 5        | Rate limiting            | Low    | Explicitly listed as bonus |
| 6        | CI/CD                    | Low    | Explicitly listed as bonus |
| 7        | Cloud deployment         | Medium | Submission bonus (live URL) |
| 8        | Observability            | Low    | Nice-to-have   |
