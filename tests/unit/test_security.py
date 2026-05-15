import time
from datetime import datetime, timedelta

import pytest
from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)

# ── Password hashing ───────────────────────────────────────────────────────


def test_hash_password_returns_bcrypt_string():
    h = hash_password("secret123")
    assert h.startswith("$2b$") or h.startswith("$2a$")


def test_hash_password_is_not_plaintext():
    h = hash_password("secret123")
    assert h != "secret123"


def test_hash_password_salted_different_each_time():
    """Two hashes of the same password should differ (salt randomness)."""
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2


def test_verify_password_correct():
    h = hash_password("mypassword")
    assert verify_password("mypassword", h) is True


def test_verify_password_wrong():
    h = hash_password("mypassword")
    assert verify_password("wrongpassword", h) is False


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


def test_decode_token_tampered_raises():
    token = create_access_token("alice@example.com")
    tampered = token[:-4] + "XXXX"
    with pytest.raises(JWTError):
        decode_token(tampered)


def test_decode_token_expired_raises():
    """Forge a token with exp in the past."""
    past = datetime.utcnow() - timedelta(seconds=1)
    expired_token = jwt.encode(
        {"sub": "alice@example.com", "exp": past},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(JWTError):
        decode_token(expired_token)


def test_decode_token_missing_sub_raises():
    """A valid-signature token with no 'sub' claim should raise JWTError."""
    token = jwt.encode(
        {"exp": datetime.utcnow() + timedelta(hours=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(JWTError, match="missing sub"):
        decode_token(token)
