"""Reusable validated field types."""

from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, EmailStr, Field

from app.utils.gstin import is_valid_gstin_format, normalize_gstin


def _check_bcrypt_limit(value: str) -> str:
    # bcrypt only uses the first 72 *bytes*; non-ASCII characters take 2-4 bytes each,
    # so a character-length check alone is not enough.
    if len(value.encode()) > 72:
        raise ValueError("Password is too long (max 72 bytes)")
    return value


def _check_gstin(value: str) -> str:
    if not is_valid_gstin_format(value):
        raise ValueError("Invalid GSTIN format (expected 15 characters, e.g. 27AAPFU0939F1ZV)")
    return value


# Lowercased so "Admin@Acme.com" and "admin@acme.com" are the same account.
Email = Annotated[EmailStr, AfterValidator(str.lower)]

Password = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(_check_bcrypt_limit)]

GSTIN = Annotated[
    str,
    BeforeValidator(lambda v: normalize_gstin(v) if isinstance(v, str) else v),
    AfterValidator(_check_gstin),
]
