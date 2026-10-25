import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.security import hash_password_async
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    """User management for admins. Every operation is scoped to the admin's organization."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def create_user(self, admin: User, data: UserCreate) -> User:
        if await self.users.get_by_email(data.email) is not None:
            raise ConflictError("A user with this email already exists")
        user = User(
            # Always the admin's organization, never a value from the request body,
            # so an admin cannot create users in someone else's organization.
            organization_id=admin.organization_id,
            email=data.email,
            hashed_password=await hash_password_async(data.password),
            full_name=data.full_name,
            role=data.role,
        )
        try:
            await self.users.add(user)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A user with this email already exists") from exc
        return user

    async def list_users(self, admin: User) -> Sequence[User]:
        return await self.users.list_by_organization(admin.organization_id)

    async def update_user(self, admin: User, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = await self.users.get_in_organization(admin.organization_id, user_id)
        if user is None:
            # 404, not 403: a 403 would confirm that this id exists in another organization.
            raise NotFoundError("User not found")

        # exclude_unset: PATCH semantics, only fields present in the request.
        # exclude_none: an explicit null means "no change" (these columns are NOT NULL).
        changes = data.model_dump(exclude_unset=True, exclude_none=True)

        # Lockout protection: an admin must not remove their own admin access,
        # which could leave the organization with no admin at all.
        if user.id == admin.id and (
            changes.get("role", UserRole.ADMIN) != UserRole.ADMIN
            or changes.get("is_active") is False
        ):
            raise BadRequestError("You cannot remove your own admin access or deactivate yourself")

        for field, value in changes.items():
            setattr(user, field, value)
        await self.session.commit()
        return user
