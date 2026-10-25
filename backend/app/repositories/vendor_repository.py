import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import Vendor


class VendorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(self, organization_id: uuid.UUID, gstin: str, name: str) -> Vendor:
        """Race-safe find-or-create.

        INSERT ... ON CONFLICT DO NOTHING relies on the unique (organization_id, gstin)
        constraint: if two workers create the same vendor at once, one insert is a
        no-op instead of an error. Then we read whichever row exists.
        """
        await self.session.execute(
            insert(Vendor)
            .values(id=uuid.uuid4(), organization_id=organization_id, gstin=gstin, name=name)
            .on_conflict_do_nothing(index_elements=["organization_id", "gstin"])
        )
        result = await self.session.execute(
            select(Vendor).where(Vendor.organization_id == organization_id, Vendor.gstin == gstin)
        )
        return result.scalar_one()

    async def get(self, organization_id: uuid.UUID, vendor_id: uuid.UUID) -> Vendor | None:
        result = await self.session.execute(
            select(Vendor).where(Vendor.id == vendor_id, Vendor.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def list(self, organization_id: uuid.UUID) -> Sequence[Vendor]:
        result = await self.session.execute(
            select(Vendor).where(Vendor.organization_id == organization_id).order_by(Vendor.name)
        )
        return result.scalars().all()
