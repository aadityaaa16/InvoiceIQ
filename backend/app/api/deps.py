"""Shared FastAPI dependencies: DB session, current user, role checks.

FastAPI resolves a dependency once per request and reuses the result, so the
route, get_current_user and the services all share the same DB session.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import TokenType, decode_token
from app.db.redis import redis_client
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository

# auto_error=False: we raise our own AuthenticationError (consistent error format, 401)
# instead of FastAPI's default response. It also adds the "Authorize" button to /docs.
bearer_scheme = HTTPBearer(auto_error=False, description="Access token from /auth/login")

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_redis() -> Redis:
    return redis_client


RedisClient = Annotated[Redis, Depends(get_redis)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise AuthenticationError("Not authenticated")
    payload = decode_token(credentials.credentials, TokenType.ACCESS)

    # Load the user on every request (a primary-key lookup, ~1 ms) instead of trusting
    # the token alone: a deactivated user is locked out immediately, not 15 minutes later
    # when their access token expires, and role changes apply right away.
    user = await UserRepository(db).get_by_id(uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: require_roles(UserRole.ADMIN) only lets admins through."""

    async def check_role(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError(f"This action requires role: {', '.join(roles)}")
        return user

    return check_role


AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
ReviewerUser = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.REVIEWER))]
