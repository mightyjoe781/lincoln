import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import hash_password
from app.db.models.user import User


@pytest.mark.asyncio
async def test_register_creates_user(unauthed_client: AsyncClient):
    resp = await unauthed_client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "secret123"},
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@example.com"


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(unauthed_client: AsyncClient, db):
    user = User(email="dup@example.com", hashed_password=hash_password("secret123"))
    db.add(user)
    await db.commit()

    resp = await unauthed_client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "secret123"},
    )
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_with_token_set_missing_header_returns_403(
    unauthed_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "registration_token", "super-secret")

    resp = await unauthed_client.post(
        "/api/v1/auth/register",
        json={"email": "token_user@example.com", "password": "secret123"},
    )
    assert resp.status_code == 403
    assert "registration token" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_with_token_set_correct_header_returns_201(
    unauthed_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "registration_token", "super-secret")

    resp = await unauthed_client.post(
        "/api/v1/auth/register",
        json={"email": "token_ok@example.com", "password": "secret123"},
        headers={"X-Registration-Token": "super-secret"},
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "token_ok@example.com"


@pytest.mark.asyncio
async def test_login_valid_credentials_returns_token(unauthed_client: AsyncClient, db):
    user = User(email="login@example.com", hashed_password=hash_password("correct-pass"))
    db.add(user)
    await db.commit()

    resp = await unauthed_client.post(
        "/api/v1/auth/token",
        data={"username": "login@example.com", "password": "correct-pass"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(unauthed_client: AsyncClient, db):
    user = User(email="wrongpass@example.com", hashed_password=hash_password("correct-pass"))
    db.add(user)
    await db.commit()

    resp = await unauthed_client.post(
        "/api/v1/auth/token",
        data={"username": "wrongpass@example.com", "password": "bad-pass"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401(unauthed_client: AsyncClient):
    resp = await unauthed_client.post(
        "/api/v1/auth/token",
        data={"username": "ghost@example.com", "password": "whatever"},
    )
    assert resp.status_code == 401
