"""Enums shared by models and Pydantic schemas.

StrEnum members are real strings, so they serialize to JSON and compare with
plain strings ("approved" == InvoiceStatus.APPROVED) without conversion.
"""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"  # manages users, can do everything
    REVIEWER = "reviewer"  # corrects, approves and rejects invoices
    UPLOADER = "uploader"  # uploads invoices and views their status


class InvoiceStatus(StrEnum):
    QUEUED = "queued"  # uploaded, waiting for the worker
    PROCESSING = "processing"  # worker is running OCR + LLM extraction
    NEEDS_REVIEW = "needs_review"  # validation failed or confidence too low
    APPROVED = "approved"  # auto-approved or approved by a reviewer
    REJECTED = "rejected"  # rejected by a reviewer
    FAILED = "failed"  # extraction failed after all retries


class ReconciliationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MatchStatus(StrEnum):
    MATCHED = "matched"  # in books and GSTR-2B, amounts agree
    AMOUNT_MISMATCH = "amount_mismatch"  # in both, amounts differ beyond tolerance
    MISSING_IN_GSTR = "missing_in_gstr"  # in our books only: supplier has not filed it
    MISSING_IN_BOOKS = "missing_in_books"  # in GSTR-2B only: we never recorded it
