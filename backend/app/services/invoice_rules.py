"""Validation + duplicate check + approval decision, shared by the pipeline
(automatic) and the review service (after a human edits an invoice)."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.invoice import Invoice
from app.repositories.invoice_repository import InvoiceRepository
from app.services.validation import InvoiceFields, ValidationIssue, validate_invoice


async def check_invoice(
    session: AsyncSession, invoice: Invoice, vendor_gstin: str | None
) -> list[ValidationIssue]:
    """All rules for one invoice. invoice.line_items must already be loaded."""
    issues = validate_invoice(
        InvoiceFields(
            vendor_gstin=vendor_gstin,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            line_item_amounts=[item.amount for item in invoice.line_items],
            subtotal=invoice.subtotal,
            cgst=invoice.cgst,
            sgst=invoice.sgst,
            igst=invoice.igst,
            total_amount=invoice.total_amount,
        ),
        today=datetime.now(UTC).date(),
        tolerance=settings.AMOUNT_TOLERANCE,
    )
    if invoice.vendor_id and invoice.invoice_number:
        duplicate_id = await InvoiceRepository(session).find_duplicate(invoice)
        if duplicate_id:
            issues.append(
                ValidationIssue(
                    "possible_duplicate",
                    "invoice_number",
                    f"Invoice {invoice.invoice_number} from this vendor already exists "
                    f"(id {duplicate_id})",
                )
            )
    return issues


def can_auto_approve(issues: list[ValidationIssue], confidence: float | None) -> bool:
    """Auto-approve only when every rule passes AND the model was confident."""
    return not issues and (confidence or 0.0) >= settings.AUTO_APPROVE_CONFIDENCE_THRESHOLD
