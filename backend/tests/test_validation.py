"""Unit tests for every validation rule (pure functions, no DB)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.services.validation import InvoiceFields, validate_invoice
from app.utils.gstin import gstin_checksum, is_valid_gstin

TODAY = date(2026, 10, 25)
D = Decimal

VALID = InvoiceFields(
    vendor_gstin="27AAPFU0939F1ZV",
    invoice_number="INV-001",
    invoice_date=date(2026, 9, 15),
    line_item_amounts=[D("600"), D("400")],
    subtotal=D("1000"),
    cgst=D("90"),
    sgst=D("90"),
    igst=None,
    total_amount=D("1180"),
)


def codes(fields: InvoiceFields) -> list[str]:
    return [i.code for i in validate_invoice(fields, today=TODAY, tolerance=D("1.00"))]


def test_valid_invoice_has_no_issues() -> None:
    assert codes(VALID) == []


def test_inter_state_igst_invoice_is_valid() -> None:
    assert codes(replace(VALID, cgst=None, sgst=None, igst=D("180"))) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"vendor_gstin": None}, ["missing_field"]),
        ({"vendor_gstin": "27AAPFU0939F1Z"}, ["invalid_gstin"]),  # 14 chars
        ({"vendor_gstin": "27AAPFU0939F1ZX"}, ["invalid_gstin"]),  # bad checksum
        ({"invoice_number": None}, ["missing_field"]),
        ({"invoice_date": date(2026, 11, 1)}, ["future_date"]),
        ({"line_item_amounts": [D("600"), D("300")]}, ["line_items_mismatch"]),
        ({"total_amount": D("1200")}, ["total_mismatch"]),
        ({"cgst": D("80"), "total_amount": D("1170")}, ["cgst_sgst_mismatch"]),
        ({"igst": D("180"), "total_amount": D("1360")}, ["igst_with_cgst_sgst"]),
    ],
)
def test_each_rule(change: dict[str, Any], expected: list[str]) -> None:
    assert codes(replace(VALID, **change)) == expected


def test_rounding_within_tolerance_is_accepted() -> None:
    assert codes(replace(VALID, total_amount=D("1180.60"))) == []


def test_gstin_checksum() -> None:
    assert is_valid_gstin("27AAPFU0939F1ZV")
    assert gstin_checksum("27AAPFU0939F1Z") == "V"
    # A single misread character is caught by the checksum.
    assert not is_valid_gstin("27AAPFU0939F1ZV".replace("U", "V"))
