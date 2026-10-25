"""Password hashing (bcrypt) and JWT creation/verification."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import AuthenticationError

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
# bcrypt is deliberately slow (~200 ms per hash) so stolen hashes are expensive to
# brute-force. The salt is random per password and stored inside the hash string.


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed_password.encode())
    except ValueError:  # malformed hash or password over bcrypt's 72-byte limit
        return False


# bcrypt is CPU-bound and would block the event loop (and every other request) for
# ~200 ms. These wrappers run it in a worker thread instead.
async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, hashed_password: str) -> bool:
    return await asyncio.to_thread(verify_password, password, hashed_password)


# Used when a login email does not exist: we still run a bcrypt check so that
# "unknown email" takes as long as "wrong password". Otherwise response timing
# would reveal which emails are registered (user enumeration).
DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-safety")


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
class TokenType(StrEnum):
    ACCESS = "access"  # short-lived (15 min), sent with every API request
    REFRESH = "refresh"  # long-lived (7 days), only used to get new access tokens


def _create_token(
    subject: uuid.UUID,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),  # who the token is about (user id)
        "type": token_type.value,  # stops a refresh token being used as an access token
        "iat": now,  # issued at
        "exp": now + expires_delta,  # expiry, checked automatically by jwt.decode
        "jti": uuid.uuid4().hex,  # unique token id, used for refresh-token rotation
        **(extra_claims or {}),
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY.get_secret_value(), algorithm=settings.JWT_ALGORITHM
    )


def create_access_token(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    return _create_token(
        user_id,
        TokenType.ACCESS,
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        {"org": str(organization_id), "role": role},
    )


def create_refresh_token(user_id: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    return _create_token(
        user_id,
        TokenType.REFRESH,
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Verify signature, expiry and type. Raises AuthenticationError on any problem."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            # Pin the algorithm list: never trust the "alg" header sent by the client
            # (the classic "alg: none" attack would otherwise skip signature checks).
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "type", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token") from exc

    if payload["type"] != expected_type:
        raise AuthenticationError("Invalid token type")
    return payload
