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


_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum(first14: str) -> str:
    """Compute the 15th (check) character of a GSTIN.

    Each character maps to 0-35; odd positions are weighted 1, even positions 2;
    each product contributes (product // 36 + product % 36). The check character
    makes the total a multiple of 36. It catches most single-character OCR errors.
    """
    total = 0
    for position, char in enumerate(first14):
        product = _CHARSET.index(char) * (1 if position % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _CHARSET[(36 - total % 36) % 36]


def is_valid_gstin(value: str) -> bool:
    """Format AND checksum."""
    return is_valid_gstin_format(value) and gstin_checksum(value[:14]) == value[14]
