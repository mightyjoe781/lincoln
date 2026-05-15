"""
Integration test configuration.

Key design:
- Tasks run eagerly by patching parse_document_task.delay to schedule
  _parse_document as an asyncio task. Tests call `await flush_tasks()` before
  asserting on post-parse state.
- A real test user is seeded into the DB so auth flows use genuine JWT validation
  against a live user row rather than dependency overrides.
- The DB fixture is inherited from the root conftest (session-scoped engine,
  function-scoped session with rollback).
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.core.security import create_access_token, hash_password
from app.db.models.user import User
from app.main import app

# Email used by integration fixtures that need a pre-existing user.
INTEGRATION_USER_EMAIL = "integration@example.com"
INTEGRATION_USER_PASSWORD = "inttest-secret-1"


# ---------------------------------------------------------------------------
# Rate-limit suppression
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def disable_rate_limiting():
    """Disable slowapi rate limiting so tests don't get throttled."""
    from app.core.limiter import limiter

    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


# ---------------------------------------------------------------------------
# Eager Celery task execution
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def run_tasks_eagerly(monkeypatch):
    """
    Patch parse_document_task.delay so that calling .delay(doc_id) schedules
    _parse_document(doc_id) as an asyncio Task on the running event loop.

    The fixture exposes the scheduled tasks via a module-level list so that
    individual tests (or the `flush_tasks` fixture) can await them.

    Because _parse_document creates its own SQLAlchemy engine using
    settings.database_url, the DATABASE_URL environment variable must point to
    the test database (the root conftest already creates the schema there).
    """
    from app.worker import tasks as task_module

    pending: list[asyncio.Task] = []

    class _EagerProxy:
        @staticmethod
        def delay(document_id: str):
            loop = asyncio.get_event_loop()
            task = loop.create_task(task_module._parse_document(document_id))
            pending.append(task)

    monkeypatch.setattr(
        "app.services.document_service.parse_document_task",
        _EagerProxy(),
    )

    # Store on the module so flush_tasks can reach it without extra fixture
    # plumbing.
    task_module._integration_pending_tasks = pending
    yield pending
    task_module._integration_pending_tasks = []


@pytest_asyncio.fixture
async def flush_tasks(run_tasks_eagerly):
    """
    Async callable that awaits all pending eager tasks.

    Usage inside a test::

        await flush_tasks()
    """
    pending = run_tasks_eagerly

    async def _flush():
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()

    return _flush


# ---------------------------------------------------------------------------
# Integration HTTP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def int_client(db):
    """AsyncClient wired to the app with the test DB session injected."""

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Pre-seeded test user & auth headers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def integration_user(db) -> User:
    """
    Insert (or reuse) the integration test user in the test DB.

    The user is committed so that the task worker (which opens its own session)
    can find it, and rolled back at end of test via the parent `db` fixture.
    """
    from sqlalchemy import select

    existing = await db.scalar(select(User).where(User.email == INTEGRATION_USER_EMAIL))
    if existing:
        return existing

    user = User(
        id=uuid.uuid4(),
        email=INTEGRATION_USER_EMAIL,
        hashed_password=hash_password(INTEGRATION_USER_PASSWORD),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture
def auth_headers(integration_user) -> dict:
    """Bearer token headers for the pre-seeded integration user."""
    token = create_access_token(integration_user.email)
    return {"Authorization": f"Bearer {token}"}
