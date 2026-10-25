"""Unit tests for password hashing and JWT handling (no database needed)."""

import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse")
    assert hashed != "correct horse"  # never stored in plain text
    assert verify_password("correct horse", hashed)
    assert not verify_password("wrong horse", hashed)


def test_same_password_gets_different_hashes() -> None:
    # Random salt per hash: identical passwords are not identifiable in the DB.
    assert hash_password("same") != hash_password("same")


def test_access_token_roundtrip() -> None:
    user_id, org_id = uuid.uuid4(), uuid.uuid4()
    payload = decode_token(create_access_token(user_id, org_id, "admin"), TokenType.ACCESS)
    assert payload["sub"] == str(user_id)
    assert payload["org"] == str(org_id)
    assert payload["role"] == "admin"


def test_refresh_token_cannot_be_used_as_access_token() -> None:
    token = create_refresh_token(uuid.uuid4())
    with pytest.raises(AuthenticationError, match="Invalid token type"):
        decode_token(token, TokenType.ACCESS)


def test_expired_token_is_rejected() -> None:
    token = create_access_token(uuid.uuid4(), uuid.uuid4(), "admin", timedelta(seconds=-1))
    with pytest.raises(AuthenticationError, match="expired"):
        decode_token(token, TokenType.ACCESS)


def test_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": 0, "exp": 9999999999, "jti": "x"},
        "attacker-key-that-is-long-enough-for-hs256",
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(AuthenticationError, match="Invalid token"):
        decode_token(forged, TokenType.ACCESS)


def test_unsigned_alg_none_token_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": 0, "exp": 9999999999, "jti": "x"},
        key=None,
        algorithm="none",
    )
    with pytest.raises(AuthenticationError):
        decode_token(forged, TokenType.ACCESS)
