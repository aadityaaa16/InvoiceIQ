import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole
from app.schemas.common import Email, Password
from app.schemas.organization import OrganizationRead


class UserRead(BaseModel):
    """Public view of a user. hashed_password is deliberately absent, so it can
    never leak through an API response, whatever an endpoint returns."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class MeResponse(UserRead):
    organization: OrganizationRead


class UserCreate(BaseModel):
    """Admin creates a user inside their own organization."""

    email: Email
    full_name: str = Field(min_length=1, max_length=255)
    password: Password
    role: UserRole = UserRole.UPLOADER  # least privilege by default


class UserUpdate(BaseModel):
    """Partial update (PATCH): only the fields sent are changed."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None
