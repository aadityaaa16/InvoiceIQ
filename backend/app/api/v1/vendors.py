"""Vendors are created automatically by the pipeline; these routes are read-only."""

import uuid
from collections.abc import Sequence

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.models.vendor import Vendor
from app.repositories.vendor_repository import VendorRepository
from app.schemas.invoice import VendorRead

router = APIRouter(prefix="/vendors", tags=["vendors"])


# Plain lookups with no business rules, so a service layer would add nothing here.
@router.get("", response_model=list[VendorRead])
async def list_vendors(user: CurrentUser, db: DbSession) -> Sequence[Vendor]:
    return await VendorRepository(db).list(user.organization_id)


@router.get("/{vendor_id}", response_model=VendorRead)
async def get_vendor(vendor_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Vendor:
    vendor = await VendorRepository(db).get(user.organization_id, vendor_id)
    if vendor is None:
        raise NotFoundError("Vendor not found")
    return vendor
