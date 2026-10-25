"""GSTIN (Goods and Services Tax Identification Number) helpers.

A GSTIN has 15 characters, e.g. 27AAPFU0939F1ZV:
    27          state code (2 digits)
    AAPFU0939F  PAN of the business (5 letters, 4 digits, 1 letter)
    1           entity number for the same PAN in that state (1-9, then A-Z)
    Z           fixed character
    V           checksum character
"""

import re

GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def normalize_gstin(value: str) -> str:
    """Uppercase and strip spaces, since OCR and users often add them."""
    return value.replace(" ", "").strip().upper()


def is_valid_gstin_format(value: str) -> bool:
    return bool(GSTIN_PATTERN.fullmatch(value))
