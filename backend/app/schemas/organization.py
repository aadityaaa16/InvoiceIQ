import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OrganizationRead(BaseModel):
    # from_attributes: build this schema directly from a SQLAlchemy object.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    gstin: str | None
    created_at: datetime
