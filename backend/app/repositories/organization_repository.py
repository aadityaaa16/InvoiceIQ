import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return await self.session.get(Organization, organization_id)

    async def add(self, organization: Organization) -> Organization:
        self.session.add(organization)
        # flush sends the INSERT now (inside the open transaction) without committing,
        # so the caller gets constraint errors immediately and can still roll back.
        await self.session.flush()
        return organization
