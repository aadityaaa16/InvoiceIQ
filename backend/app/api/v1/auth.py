"""Auth routes. Routes only translate HTTP <-> service calls; no business logic here."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, DbSession, RedisClient
from app.core.config import settings
from app.core.rate_limit import limiter
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenPair
from app.schemas.user import MeResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(db: DbSession, redis: RedisClient) -> AuthService:
    return AuthService(db, redis)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


# SlowAPI needs the `request` parameter to read the client IP.
@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.LOGIN_RATE_LIMIT)
async def register(request: Request, data: RegisterRequest, service: AuthServiceDep) -> TokenPair:
    """Create a new organization and its admin user, and log them in."""
    return await service.register(data)


@router.post("/login")
@limiter.limit(settings.LOGIN_RATE_LIMIT)
async def login(request: Request, data: LoginRequest, service: AuthServiceDep) -> TokenPair:
    return await service.login(data.email, data.password)


@router.post("/refresh")
async def refresh(data: RefreshRequest, service: AuthServiceDep) -> TokenPair:
    """Exchange a refresh token for a new pair. Each refresh token can be used once."""
    return await service.refresh(data.refresh_token)


@router.get("/me")
async def me(user: CurrentUser, service: AuthServiceDep) -> MeResponse:
    return await service.get_profile(user)
