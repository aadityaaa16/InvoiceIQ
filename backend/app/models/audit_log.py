import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only record of who changed what. Rows are never updated or deleted.

    Generic (entity_type + entity_id) rather than one table per entity, so any
    model can be audited without a schema change.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        # "Show the history of invoice X" is the main query.
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # Nullable: system actions (e.g. auto-approval by the pipeline) have no user.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))  # e.g. "invoice"
    entity_id: Mapped[uuid.UUID]
    action: Mapped[str] = mapped_column(String(50))  # e.g. "update", "approve"
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
