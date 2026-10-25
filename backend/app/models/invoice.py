import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import InvoiceStatus

if TYPE_CHECKING:
    from app.models.vendor import Vendor

# Money: up to 999,999,999,999.99 with exact decimal arithmetic. Never use float for
# money — 0.1 + 0.2 != 0.3 in floating point, which would break "totals add up" checks.
Money = Numeric(14, 2)


class Invoice(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # Composite indexes lead with organization_id because every query is tenant-scoped,
        # e.g. WHERE organization_id = ? AND status = ? ORDER BY created_at.
        Index("ix_invoices_org_status", "organization_id", "status"),
        Index("ix_invoices_org_created_at", "organization_id", "created_at"),
        # Fast lookup for the pipeline's duplicate check (across all statuses).
        Index("ix_invoices_org_vendor_number", "organization_id", "vendor_id", "invoice_number"),
        # Partial unique index: the same vendor invoice can never be APPROVED twice in one
        # organization, which is what prevents duplicate payments. It is partial so a
        # suspected duplicate can still be stored as needs_review for a human to inspect,
        # and so a rejected copy does not block a later correct upload. The service layer
        # flags duplicates first; this index is the database-level guarantee against races.
        Index(
            "uq_invoices_approved_org_vendor_number",
            "organization_id",
            "vendor_id",
            "invoice_number",
            unique=True,
            postgresql_where="status = 'approved'",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    # Nullable: unknown until extraction finds the vendor's GSTIN.
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)

    # --- Original file ---
    file_key: Mapped[str] = mapped_column(String(512))  # object key in S3 storage
    original_filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))  # pdf, jpg, png

    status: Mapped[InvoiceStatus] = mapped_column(
        enum_column(InvoiceStatus, "invoice_status"),
        default=InvoiceStatus.QUEUED,
        server_default=InvoiceStatus.QUEUED.value,
    )

    # --- Extracted fields (all nullable: filled in by the pipeline) ---
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    cgst: Mapped[Decimal | None] = mapped_column(Money)
    sgst: Mapped[Decimal | None] = mapped_column(Money)
    igst: Mapped[Decimal | None] = mapped_column(Money)
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    # A score in [0, 1], not money, so float is fine here.
    confidence_score: Mapped[float | None] = mapped_column(Float)

    # --- Pipeline outputs, kept for debugging and evaluation ---
    raw_ocr_text: Mapped[str | None] = mapped_column(Text)
    # JSONB: stored in binary form, so it can be indexed and queried (e.g. ->> 'field').
    raw_llm_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # onupdate is applied by the ORM whenever the row is updated through SQLAlchemy.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # When extraction + validation finished; processed_at - created_at = processing time.
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # lazy="raise": in async code an implicit lazy load would fail or cause N+1 queries.
    # This forces every query to load relations explicitly with selectinload().
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",  # line items live and die with their invoice
        lazy="raise",
    )
    vendor: Mapped["Vendor | None"] = relationship(lazy="raise")


class InvoiceLineItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "invoice_line_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    hsn_code: Mapped[str | None] = mapped_column(String(8))  # HSN/SAC goods/services code
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # e.g. 2.5 kg
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # percent, e.g. 18.00
    amount: Mapped[Decimal] = mapped_column(Money)

    invoice: Mapped[Invoice] = relationship(back_populates="line_items", lazy="raise")
