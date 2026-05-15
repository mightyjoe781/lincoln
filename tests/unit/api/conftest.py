import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db
from app.core.limiter import limiter
from app.db.models.user import User
from app.main import app


@pytest.fixture(autouse=True)
def disable_rate_limiting():
    """Disable slowapi rate limiting during API tests."""
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest_asyncio.fixture
async def client(db):
    async def override_get_db():
        yield db

    fake_user = User(email="test@example.com", hashed_password="hashed")

    async def override_get_current_user():
        return fake_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauthed_client(db):
    """Client with DB override but no auth override — used to test 401 responses."""

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
