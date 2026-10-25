import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Vendor(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A supplier, created automatically the first time its GSTIN appears on an invoice."""

    __tablename__ = "vendors"
    # One vendor per GSTIN *per organization*: two businesses can buy from the same
    # supplier, and each gets its own vendor row. The constraint also makes
    # "find or create vendor" race-safe (a concurrent duplicate insert fails).
    # Its leading column also serves as the index on organization_id.
    __table_args__ = (UniqueConstraint("organization_id", "gstin"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    gstin: Mapped[str] = mapped_column(String(15))
