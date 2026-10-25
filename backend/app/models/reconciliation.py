import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import MatchStatus, ReconciliationStatus


class ReconciliationRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One upload of a GSTR-2B file for a tax period, matched against approved invoices."""

    __tablename__ = "reconciliation_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    period: Mapped[str] = mapped_column(String(7))  # "YYYY-MM", e.g. "2026-09"
    file_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[ReconciliationStatus] = mapped_column(
        enum_column(ReconciliationStatus, "reconciliation_status"),
        default=ReconciliationStatus.PENDING,
        server_default=ReconciliationStatus.PENDING.value,
    )
    # Counts per match status and totals, computed once so the list view is cheap.
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)

    results: Mapped[list["ReconciliationResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="raise"
    )


class ReconciliationResult(UUIDPrimaryKeyMixin, Base):
    """One matched (or unmatched) record within a run."""

    __tablename__ = "reconciliation_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    # Null for missing_in_books (the record exists only in GSTR-2B).
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )
    # The raw GSTR-2B row; null for missing_in_gstr (the invoice exists only in our books).
    gstr_record: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    match_status: Mapped[MatchStatus] = mapped_column(enum_column(MatchStatus, "match_status"))
    difference_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    run: Mapped[ReconciliationRun] = relationship(back_populates="results", lazy="raise")
