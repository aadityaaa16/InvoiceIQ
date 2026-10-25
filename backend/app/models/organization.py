from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A business using InvoiceIQ (the tenant). Every other row belongs to one."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255))
    gstin: Mapped[str | None] = mapped_column(String(15))
