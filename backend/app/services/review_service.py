"""Human review: corrections, approval and rejection, each recorded in the audit log."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice, InvoiceLineItem
from app.models.user import User
from app.repositories.audit_repository import AuditRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.vendor_repository import VendorRepository
from app.schemas.invoice import InvoiceUpdate
from app.services.invoice_rules import check_invoice

_SCALAR_FIELDS = (
    "invoice_number",
    "invoice_date",
    "subtotal",
    "cgst",
    "sgst",
    "igst",
    "total_amount",
)


def _line_items_snapshot(invoice: Invoice) -> list[dict[str, Any]]:
    return [{"description": i.description, "amount": i.amount} for i in invoice.line_items]


class ReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.invoices = InvoiceRepository(session)
        self.vendors = VendorRepository(session)
        self.audit = AuditRepository(session)

    async def _get_for_review(self, user: User, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self.invoices.get_with_details(user.organization_id, invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        if invoice.status != InvoiceStatus.NEEDS_REVIEW:
            # State machine: only invoices awaiting review can be edited/approved/rejected.
            raise ConflictError(f"Invoice is '{invoice.status}', not awaiting review")
        return invoice

    async def update(self, user: User, invoice_id: uuid.UUID, data: InvoiceUpdate) -> Invoice:
        invoice = await self._get_for_review(user, invoice_id)
        changes = data.model_dump(exclude_unset=True)
        old: dict[str, Any] = {}
        new: dict[str, Any] = {}

        if "vendor_gstin" in changes and changes["vendor_gstin"]:
            vendor = await self.vendors.get_or_create(
                invoice.organization_id,
                changes["vendor_gstin"],
                changes.get("vendor_name") or changes["vendor_gstin"],
            )
            if vendor.id != invoice.vendor_id:
                old["vendor_id"], new["vendor_id"] = invoice.vendor_id, vendor.id
                invoice.vendor_id = vendor.id
        elif changes.get("vendor_name") and invoice.vendor is not None:
            old["vendor_name"], new["vendor_name"] = invoice.vendor.name, changes["vendor_name"]
            invoice.vendor.name = changes["vendor_name"]

        for field in _SCALAR_FIELDS:
            if field in changes and changes[field] != getattr(invoice, field):
                old[field], new[field] = getattr(invoice, field), changes[field]
                setattr(invoice, field, changes[field])

        if changes.get("line_items") is not None:
            old["line_items"] = _line_items_snapshot(invoice)
            invoice.line_items = [InvoiceLineItem(**item) for item in changes["line_items"]]
            new["line_items"] = _line_items_snapshot(invoice)

        await self.session.flush()
        # Re-run every rule on the corrected data, so the reviewer sees what's still wrong.
        current_vendor = (
            await self.vendors.get(invoice.organization_id, invoice.vendor_id)
            if invoice.vendor_id
            else None
        )
        gstin = (
            current_vendor.gstin
            if current_vendor
            else (invoice.raw_llm_output or {}).get("vendor_gstin")
        )
        issues = await check_invoice(self.session, invoice, gstin)
        invoice.validation_errors = [issue.to_dict() for issue in issues]

        if new:
            # Old AND new values: who changed what, from what, to what.
            await self.audit.record(
                organization_id=invoice.organization_id,
                user_id=user.id,
                entity_id=invoice.id,
                action="update",
                old_values=old,
                new_values=new,
            )
        await self.session.commit()
        # updated_at is computed by the DB (onupdate=now()), so it must be re-read too.
        await self.session.refresh(invoice, ["updated_at", "vendor", "line_items"])
        return invoice

    async def approve(self, user: User, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self._get_for_review(user, invoice_id)
        open_issues = len(invoice.validation_errors or [])
        invoice.status = InvoiceStatus.APPROVED
        invoice.approved_by = user.id
        invoice.approved_at = datetime.now(UTC)
        await self.audit.record(
            organization_id=invoice.organization_id,
            user_id=user.id,
            entity_id=invoice.id,
            action="approve",
            old_values={"status": "needs_review"},
            # A reviewer may knowingly override open issues; the log records that.
            new_values={"status": "approved", "overridden_issues": open_issues},
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            # Partial unique index: this vendor invoice is already approved.
            await self.session.rollback()
            raise ConflictError(
                "An invoice with this number from this vendor is already approved"
            ) from exc
        return invoice

    async def reject(self, user: User, invoice_id: uuid.UUID, reason: str) -> Invoice:
        invoice = await self._get_for_review(user, invoice_id)
        invoice.status = InvoiceStatus.REJECTED
        invoice.failure_reason = f"Rejected: {reason}"
        await self.audit.record(
            organization_id=invoice.organization_id,
            user_id=user.id,
            entity_id=invoice.id,
            action="reject",
            old_values={"status": "needs_review"},
            new_values={"status": "rejected", "reason": reason},
        )
        await self.session.commit()
        return invoice
