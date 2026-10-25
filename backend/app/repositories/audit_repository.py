import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


def _json_safe(values: dict[str, Any] | None) -> dict[str, Any] | None:
    """Decimals, dates and UUIDs become strings so they can be stored as JSONB."""
    return None if values is None else json.loads(json.dumps(values, default=str))


class AuditRepository:
    """Append-only: rows are added, never updated or deleted."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        entity_id: uuid.UUID,
        action: str,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
        entity_type: str = "invoice",
    ) -> None:
        # Added to the caller's transaction: the change and its audit row commit together.
        self.session.add(
            AuditLog(
                organization_id=organization_id,
                user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                old_values=_json_safe(old_values),
                new_values=_json_safe(new_values),
            )
        )
