import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """All user queries. Repositories flush but never commit: the service owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Unscoped lookup, only for authentication (the token says who the user is)."""
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_in_organization(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> User | None:
        """Tenant-scoped lookup: a user in another organization is simply not found."""
        result = await self.session.execute(
            select(User).where(User.id == user_id, User.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def list_by_organization(self, organization_id: uuid.UUID) -> Sequence[User]:
        result = await self.session.execute(
            select(User).where(User.organization_id == organization_id).order_by(User.created_at)
        )
        return result.scalars().all()

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user
