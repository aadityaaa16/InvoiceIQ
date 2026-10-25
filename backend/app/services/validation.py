"""Rule-based invoice validation: we never trust the LLM's output blindly.

Pure functions (no DB, no I/O), so every rule is trivially unit-testable.
The duplicate check needs the database and lives in the pipeline/review service.
"""

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from app.utils.gstin import is_valid_gstin, is_valid_gstin_format


@dataclass(frozen=True)
class ValidationIssue:
    code: str  # stable, machine-readable (the frontend can map it to help text)
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class InvoiceFields:
    vendor_gstin: str | None
    invoice_number: str | None
    invoice_date: date | None
    line_item_amounts: list[Decimal]
    subtotal: Decimal | None
    cgst: Decimal | None
    sgst: Decimal | None
    igst: Decimal | None
    total_amount: Decimal | None


def _zero(value: Decimal | None) -> Decimal:
    return value or Decimal("0")


def validate_invoice(
    fields: InvoiceFields, *, today: date, tolerance: Decimal
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(code: str, field: str, message: str) -> None:
        issues.append(ValidationIssue(code, field, message))

    # --- Required fields ---
    if not fields.invoice_number:
        add("missing_field", "invoice_number", "Invoice number is missing")
    if fields.total_amount is None:
        add("missing_field", "total_amount", "Total amount is missing")

    # --- GSTIN: structure, then checksum (catches most single-character OCR errors) ---
    if not fields.vendor_gstin:
        add("missing_field", "vendor_gstin", "Vendor GSTIN is missing")
    elif not is_valid_gstin_format(fields.vendor_gstin):
        add("invalid_gstin", "vendor_gstin", f"'{fields.vendor_gstin}' is not a valid GSTIN format")
    elif not is_valid_gstin(fields.vendor_gstin):
        add("invalid_gstin", "vendor_gstin", "GSTIN checksum does not match (likely an OCR error)")

    # --- Date ---
    if fields.invoice_date is None:
        add("missing_field", "invoice_date", "Invoice date is missing")
    elif fields.invoice_date > today:
        add("future_date", "invoice_date", f"Invoice date {fields.invoice_date} is in the future")

    # --- Amounts add up (with a small rounding tolerance) ---
    if fields.line_item_amounts and fields.subtotal is not None:
        items_sum = sum(fields.line_item_amounts, Decimal("0"))
        if abs(items_sum - fields.subtotal) > tolerance:
            add(
                "line_items_mismatch",
                "subtotal",
                f"Line items sum to {items_sum}, but subtotal is {fields.subtotal}",
            )

    if fields.subtotal is not None and fields.total_amount is not None:
        expected = fields.subtotal + _zero(fields.cgst) + _zero(fields.sgst) + _zero(fields.igst)
        if abs(expected - fields.total_amount) > tolerance:
            add(
                "total_mismatch",
                "total_amount",
                f"Subtotal + taxes = {expected}, but total is {fields.total_amount}",
            )

    # --- GST structure: intra-state = CGST + SGST (equal halves); inter-state = IGST only ---
    has_cgst_sgst = bool(_zero(fields.cgst) or _zero(fields.sgst))
    if has_cgst_sgst and abs(_zero(fields.cgst) - _zero(fields.sgst)) > tolerance:
        add("cgst_sgst_mismatch", "cgst", f"CGST {fields.cgst} and SGST {fields.sgst} differ")
    if has_cgst_sgst and _zero(fields.igst):
        add("igst_with_cgst_sgst", "igst", "IGST cannot be charged together with CGST/SGST")

    return issues
