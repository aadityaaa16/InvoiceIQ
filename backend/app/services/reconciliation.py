"""Matching logic: our approved invoices ("books") vs. GSTR-2B (what suppliers filed).

Pure function, no DB, so every case is unit-testable. Why it matters: a business
can only claim input tax credit (ITC) for invoices its supplier actually reported
to the GST portal, so "missing in GSTR-2B" means tax credit at risk.
"""

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models.enums import MatchStatus
from app.services.gstr2b_parser import GstrRecord


@dataclass(frozen=True)
class BookEntry:
    invoice_id: uuid.UUID
    vendor_gstin: str
    invoice_number: str
    total_amount: Decimal
    total_tax: Decimal


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    invoice_id: uuid.UUID | None
    gstr_record: GstrRecord | None
    difference: Decimal | None  # books minus GSTR, for amount mismatches


def normalize_invoice_number(value: str) -> str:
    """'INV-001', 'inv 001' and 'INV/001' are the same invoice. Suppliers and OCR
    format numbers inconsistently, so compare only letters and digits."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _key(gstin: str, invoice_number: str) -> tuple[str, str]:
    return gstin.upper(), normalize_invoice_number(invoice_number)


def reconcile(
    books: list[BookEntry], gstr: list[GstrRecord], tolerance: Decimal
) -> list[MatchResult]:
    # Dict lookup: O(n + m) overall instead of comparing every pair (O(n * m)).
    unmatched_books = {_key(b.vendor_gstin, b.invoice_number): b for b in books}
    results: list[MatchResult] = []

    for record in gstr:
        book = unmatched_books.pop(_key(record.supplier_gstin, record.invoice_number), None)
        if book is None:
            # In GSTR-2B but not in our approved books: never received, not yet
            # processed, or filed twice by the supplier. Worth investigating.
            results.append(MatchResult(MatchStatus.MISSING_IN_BOOKS, None, record, None))
            continue
        difference = book.total_amount - record.invoice_value
        status = (
            MatchStatus.MATCHED if abs(difference) <= tolerance else MatchStatus.AMOUNT_MISMATCH
        )
        results.append(
            MatchResult(
                status,
                book.invoice_id,
                record,
                difference if status == MatchStatus.AMOUNT_MISMATCH else None,
            )
        )

    # Left over: approved by us but not reported by the supplier, so ITC can't be claimed yet.
    results.extend(
        MatchResult(MatchStatus.MISSING_IN_GSTR, book.invoice_id, None, None)
        for book in unmatched_books.values()
    )
    return results


def summarize(results: list[MatchResult], books: list[BookEntry]) -> dict[str, Any]:
    counts = {status.value: 0 for status in MatchStatus}
    for result in results:
        counts[result.status.value] += 1
    tax_by_invoice = {b.invoice_id: b.total_tax for b in books}
    itc_at_risk = sum(
        (
            tax_by_invoice[r.invoice_id]
            for r in results
            if r.status == MatchStatus.MISSING_IN_GSTR and r.invoice_id
        ),
        Decimal("0"),
    )
    matched_itc = sum(
        (
            r.gstr_record.total_tax
            for r in results
            if r.status == MatchStatus.MATCHED and r.gstr_record
        ),
        Decimal("0"),
    )
    return {
        "counts": counts,
        "total_records": len(results),
        # Strings: JSONB has no exact decimal type; keep money exact.
        "matched_itc": str(matched_itc),
        "itc_at_risk": str(itc_at_risk),
    }
