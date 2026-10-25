import time
import uuid

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password_async,
    verify_password_async,
)
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RegisterRequest, TokenPair
from app.schemas.organization import OrganizationRead
from app.schemas.user import MeResponse, UserRead

INVALID_CREDENTIALS = "Invalid email or password"


class AuthService:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self.session = session
        self.redis = redis
        self.users = UserRepository(session)
        self.organizations = OrganizationRepository(session)

    async def register(self, data: RegisterRequest) -> TokenPair:
        """Create an organization and its first admin user in ONE transaction:
        either both rows exist afterwards, or neither does."""
        # Friendly early check. The unique constraint on email below is what actually
        # guarantees uniqueness if two sign-ups with the same email race each other.
        if await self.users.get_by_email(data.email) is not None:
            raise ConflictError("A user with this email already exists")

        organization = await self.organizations.add(
            Organization(name=data.organization_name, gstin=data.organization_gstin)
        )
        user = User(
            organization_id=organization.id,
            email=data.email,
            hashed_password=await hash_password_async(data.password),
            full_name=data.full_name,
            role=UserRole.ADMIN,
        )
        try:
            await self.users.add(user)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A user with this email already exists") from exc
        return self._issue_tokens(user)

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self.users.get_by_email(email)
        if user is None:
            # Burn the same bcrypt time as a real check, so response timing does not
            # reveal whether the email is registered.
            await verify_password_async(password, DUMMY_PASSWORD_HASH)
            raise AuthenticationError(INVALID_CREDENTIALS)
        # Same message for "no such user" and "wrong password" (no user enumeration).
        if not await verify_password_async(password, user.hashed_password):
            raise AuthenticationError(INVALID_CREDENTIALS)
        if not user.is_active:
            raise AuthenticationError("This account has been deactivated")
        return self._issue_tokens(user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        """Exchange a refresh token for a new token pair (refresh-token rotation).

        Each refresh token works exactly once. SET with NX ("only if not exists") is
        atomic in Redis, so even two simultaneous requests with the same token cannot
        both succeed. A replayed (possibly stolen) token is rejected.
        """
        payload = decode_token(refresh_token, TokenType.REFRESH)
        # Remember the token id only until it would have expired anyway.
        ttl_seconds = max(int(payload["exp"] - time.time()), 1)
        first_use = await self.redis.set(
            f"auth:refresh_used:{payload['jti']}", "1", ex=ttl_seconds, nx=True
        )
        if not first_use:
            raise AuthenticationError("Refresh token has already been used")

        # Reload the user: they may have been deactivated or had their role changed
        # since the refresh token was issued. The new access token reflects that.
        user = await self.users.get_by_id(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthenticationError("User not found or inactive")
        return self._issue_tokens(user)

    async def get_profile(self, user: User) -> MeResponse:
        organization = await self.organizations.get_by_id(user.organization_id)
        return MeResponse(
            **UserRead.model_validate(user).model_dump(),
            organization=OrganizationRead.model_validate(organization),
        )

    @staticmethod
    def _issue_tokens(user: User) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(user.id, user.organization_id, user.role),
            refresh_token=create_refresh_token(user.id),
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
