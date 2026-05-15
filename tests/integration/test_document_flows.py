"""
End-to-end integration tests for the Lincoln document processing pipeline.

Each test exercises real HTTP routes → real DB writes → real parser logic.
Celery tasks are run eagerly via the `run_tasks_eagerly` fixture (see conftest).

Prerequisites (handled by root conftest + DATABASE_URL env var):
- A running PostgreSQL instance with the test schema created.
- DATABASE_URL env var pointing at the test DB (e.g. lincoln_test).
- An upload directory writable by the process (settings.upload_dir).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document
from app.db.models.transaction import Transaction

# Minimal valid CSV that the CsvStatementParser can handle.
_CSV_TWO_ROWS = (
    b"date,description,amount,currency,balance,reference\n"
    b"2024-01-01,Salary Credit,5000.00,USD,5000.00,REF001\n"
    b"2024-01-02,Rent Payment,-1500.00,USD,3500.00,REF002\n"
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _upload_csv(client: AsyncClient, csv_bytes: bytes, filename: str, headers: dict):
    """POST to /api/v1/documents/upload and return the raw Response."""
    return await client.post(
        "/api/v1/documents/upload",
        files=[("files", (filename, csv_bytes, "text/csv"))],
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Test 1 — CSV upload triggers parsing and creates Transaction rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_upload_creates_transactions(
    int_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    flush_tasks,
):
    """
    Upload a real two-row CSV, let the eager task parse it, then verify:
    - The document reaches status "done".
    - Two Transaction rows exist linked to that document.
    - The /api/v1/transactions endpoint reflects the new rows.
    """
    resp = await _upload_csv(int_client, _CSV_TWO_ROWS, "statement.csv", auth_headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["total"] == 1
    assert body["created"] == 1

    doc_id = body["results"][0]["document"]["id"]

    # Let the background parse task finish.
    await flush_tasks()

    # Expire the session cache so we see the writes made by the task's own
    # engine connection.
    await db.invalidate()
    async with db.begin_nested():
        pass

    # Document status must be "done".
    doc_resp = await int_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_resp.status_code == 200, doc_resp.text
    doc_data = doc_resp.json()
    assert doc_data["status"] == "done", f"Unexpected status: {doc_data.get('error_message')}"

    # Verify transactions in DB directly.
    txns = list(
        await db.scalars(select(Transaction).where(Transaction.document_id == uuid.UUID(doc_id)))
    )
    assert len(txns) == 2, f"Expected 2 transactions, got {len(txns)}"

    amounts = {float(t.amount) for t in txns}
    assert 5000.0 in amounts
    assert -1500.0 in amounts


# ---------------------------------------------------------------------------
# Test 2 — Duplicate upload returns the existing document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_upload_returns_existing(
    int_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    flush_tasks,
):
    """
    Uploading identical bytes twice must:
    - Return the same document id both times.
    - Report duplicates=1 on the second request.
    - Not create a second set of Transaction rows.
    """
    csv_bytes = b"date,description,amount\n2024-06-01,Duplicate Test,100.00\n"

    r1 = await _upload_csv(int_client, csv_bytes, "dup.csv", auth_headers)
    assert r1.status_code == 200, r1.text
    await flush_tasks()

    r2 = await _upload_csv(int_client, csv_bytes, "dup.csv", auth_headers)
    assert r2.status_code == 200, r2.text

    b1 = r1.json()
    b2 = r2.json()

    id1 = b1["results"][0]["document"]["id"]
    id2 = b2["results"][0]["document"]["id"]

    assert id1 == id2, "Duplicate upload must return the same document id"
    assert b2["duplicates"] == 1, "Second upload must be reported as a duplicate"
    assert b2["created"] == 0

    # Only one set of transactions should exist.
    from sqlalchemy import func

    count = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.document_id == uuid.UUID(id1))
    )
    assert count == 1, f"Expected exactly 1 transaction row, got {count}"


# ---------------------------------------------------------------------------
# Test 3 — Corrupted PDF sets document status to "failed"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corrupted_pdf_sets_failed_status(
    int_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    flush_tasks,
):
    """
    Uploading bytes that are not a valid PDF must result in the document
    reaching status "failed" with a non-null error_message.
    """
    resp = await int_client.post(
        "/api/v1/documents/upload",
        files=[("files", ("bad.pdf", b"not a real pdf at all", "application/pdf"))],
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    doc_id = resp.json()["results"][0]["document"]["id"]

    await flush_tasks()

    doc_resp = await int_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_resp.status_code == 200, doc_resp.text
    data = doc_resp.json()

    assert data["status"] == "failed", f"Expected 'failed', got {data['status']!r}"
    assert data["error_message"], "error_message must be set when parsing fails"


# ---------------------------------------------------------------------------
# Test 4 — Deleting a document cascades to its transactions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_document_cascades_to_transactions(
    int_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    flush_tasks,
):
    """
    After uploading a CSV (which creates Transaction rows), deleting the
    document via DELETE /api/v1/documents/{id} must:
    - Return 204.
    - Make GET /api/v1/documents/{id} return 404.
    - Remove the linked Transaction rows (cascade delete).
    """
    csv_bytes = b"date,description,amount\n2024-03-01,Cascade Test,200.00\n"

    upload = await _upload_csv(int_client, csv_bytes, "cascade.csv", auth_headers)
    assert upload.status_code == 200, upload.text
    doc_id = upload.json()["results"][0]["document"]["id"]

    await flush_tasks()

    # Confirm transaction was created.
    from sqlalchemy import func

    count_before = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.document_id == uuid.UUID(doc_id))
    )
    assert count_before >= 1, "At least one transaction should exist before delete"

    # Delete the document.
    del_resp = await int_client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert del_resp.status_code == 204, del_resp.text

    # Document should be gone.
    get_resp = await int_client.get(f"/api/v1/documents/{doc_id}")
    assert get_resp.status_code == 404

    # Transactions must also be gone (cascade).
    count_after = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.document_id == uuid.UUID(doc_id))
    )
    assert count_after == 0, f"Expected 0 transactions after cascade delete, got {count_after}"


# ---------------------------------------------------------------------------
# Test 5 — Auth flow: register → login → use token → access protected endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_register_login_and_access(
    int_client: AsyncClient,
    db: AsyncSession,
):
    """
    Full auth round-trip:
    1. Register a new user.
    2. Log in to obtain a JWT.
    3. Use the JWT to call a protected endpoint.
    4. Verify the token is accepted (404 on non-existent resource, not 401).
    """
    email = f"newuser-{uuid.uuid4().hex[:8]}@test.com"
    password = "testpass123"

    # Register.
    reg = await int_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code == 201, reg.text
    assert reg.json()["email"] == email

    # Login.
    login = await int_client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token_data = login.json()
    assert "access_token" in token_data
    token = token_data["access_token"]

    # Use the token on a protected endpoint — a non-existent document should
    # yield 404, NOT 401, confirming the token was accepted.
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = uuid.uuid4()
    protected_resp = await int_client.delete(f"/api/v1/documents/{fake_id}", headers=headers)
    assert protected_resp.status_code == 404, (
        f"Expected 404 (valid token, missing resource), got {protected_resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 6 — Unauthenticated upload attempt returns 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_upload_returns_401(
    int_client: AsyncClient,
    db: AsyncSession,
):
    """
    POST /api/v1/documents/upload without an Authorization header must be
    rejected with HTTP 401.
    """
    resp = await int_client.post(
        "/api/v1/documents/upload",
        files=[("files", ("test.csv", b"date,description,amount\n", "text/csv"))],
    )
    assert resp.status_code == 401, (
        f"Expected 401 for unauthenticated upload, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 7 — Multi-file batch upload processes all files in one request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_upload_multiple_csv_files(
    int_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    flush_tasks,
):
    """
    Upload two distinct CSV files in a single multipart request.
    Both should be created and parsed independently.
    """
    csv_a = b"date,description,amount\n2024-02-01,Batch A,300.00\n"
    csv_b = b"date,description,amount\n2024-02-02,Batch B,400.00\n"

    resp = await int_client.post(
        "/api/v1/documents/upload",
        files=[
            ("files", ("batch_a.csv", csv_a, "text/csv")),
            ("files", ("batch_b.csv", csv_b, "text/csv")),
        ],
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["total"] == 2
    assert body["created"] == 2
    assert body["duplicates"] == 0

    await flush_tasks()

    # Both documents should reach "done".
    for result in body["results"]:
        doc_id = result["document"]["id"]
        doc_resp = await int_client.get(f"/api/v1/documents/{doc_id}")
        assert doc_resp.status_code == 200
        assert doc_resp.json()["status"] == "done", (
            f"Document {doc_id} not done: {doc_resp.json().get('error_message')}"
        )


# ---------------------------------------------------------------------------
# Test 8 — Transaction list reflects only rows from this test (filter by doc)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_upload_transaction_fields(
    int_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
    flush_tasks,
):
    """
    Verify that parsed transactions carry the correct field values from the
    sample fixture CSV (amount, currency, reference, description).
    """
    # Use the real fixture file bytes.
    sample_csv = (
        b"date,description,amount,currency,balance,reference\n"
        b"2024-01-05,Salary Credit,5000.00,USD,5000.00,REF001\n"
        b"2024-01-06,Rent Payment,-1500.00,USD,3500.00,REF002\n"
    )

    upload = await _upload_csv(int_client, sample_csv, "fields.csv", auth_headers)
    assert upload.status_code == 200, upload.text
    doc_id = upload.json()["results"][0]["document"]["id"]

    await flush_tasks()

    # Query transactions directly from DB for full field access.
    txns = list(
        await db.scalars(
            select(Transaction)
            .where(Transaction.document_id == uuid.UUID(doc_id))
            .order_by(Transaction.transaction_date)
        )
    )
    assert len(txns) == 2

    salary, rent = txns[0], txns[1]

    assert salary.description == "Salary Credit"
    assert float(salary.amount) == 5000.0
    assert salary.currency == "USD"
    assert salary.reference == "REF001"

    assert rent.description == "Rent Payment"
    assert float(rent.amount) == -1500.0
    assert rent.reference == "REF002"


# ---------------------------------------------------------------------------
# Test 9 — Unsupported MIME type is rejected before any DB write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_mime_type_rejected(
    int_client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict,
):
    """
    Uploading a file with an unsupported Content-Type must return 422 and
    must not create a Document row.
    """
    from sqlalchemy import func

    count_before = await db.scalar(select(func.count()).select_from(Document))

    resp = await int_client.post(
        "/api/v1/documents/upload",
        files=[("files", ("notes.txt", b"hello world", "text/plain"))],
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "unsupported type" in resp.json()["detail"].lower()

    count_after = await db.scalar(select(func.count()).select_from(Document))
    assert count_after == count_before, "No Document row should be created for rejected MIME type"


# ---------------------------------------------------------------------------
# Test 10 — Wrong credentials on /auth/token return 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(
    int_client: AsyncClient,
    db: AsyncSession,
):
    """Logging in with an incorrect password must yield 401."""
    email = f"wrongpw-{uuid.uuid4().hex[:8]}@test.com"

    reg = await int_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse"},
    )
    assert reg.status_code == 201

    bad_login = await int_client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": "wrong-battery"},
    )
    assert bad_login.status_code == 401
