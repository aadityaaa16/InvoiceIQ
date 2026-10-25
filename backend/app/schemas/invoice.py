"""Invoice request/response schemas.

Money fields are Decimal; Pydantic serializes them to JSON as strings ("1180.00"),
so no precision is lost on the way to the client (JSON numbers are floats in JS).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import InvoiceStatus
from app.schemas.common import GSTIN


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InvoiceUploadResponse(_ORMModel):
    id: uuid.UUID
    status: InvoiceStatus
    original_filename: str
    failure_reason: str | None = None


class VendorSummary(_ORMModel):
    id: uuid.UUID
    name: str
    gstin: str


class LineItemRead(_ORMModel):
    id: uuid.UUID
    description: str
    hsn_code: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    tax_rate: Decimal | None
    amount: Decimal


class InvoiceListItem(_ORMModel):
    id: uuid.UUID
    status: InvoiceStatus
    original_filename: str
    file_type: str
    invoice_number: str | None
    invoice_date: date | None
    total_amount: Decimal | None
    confidence_score: float | None
    vendor: VendorSummary | None
    created_at: datetime


class InvoiceDetail(InvoiceListItem):
    subtotal: Decimal | None
    cgst: Decimal | None
    sgst: Decimal | None
    igst: Decimal | None
    validation_errors: list[dict[str, Any]] | None
    failure_reason: str | None
    retry_count: int
    uploaded_by: uuid.UUID
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    updated_at: datetime
    line_items: list[LineItemRead]


class InvoiceStatusRead(_ORMModel):
    """Small payload for frequent polling by the frontend."""

    id: uuid.UUID
    status: InvoiceStatus
    failure_reason: str | None
    updated_at: datetime


class FileUrlResponse(BaseModel):
    url: str
    expires_in: int


class InvoiceListQuery(BaseModel):
    """Query parameters for GET /invoices, validated as one model."""

    # Unknown query parameters are rejected (422) instead of silently ignored,
    # so a typo like ?stauts=approved is noticed instead of returning everything.
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)  # capped: no "give me 1M rows"
    status: list[InvoiceStatus] | None = None  # ?status=approved&status=needs_review
    vendor_id: uuid.UUID | None = None
    date_from: date | None = None  # filters on invoice_date
    date_to: date | None = None
    # Whitelisted sort columns: user input never becomes raw SQL.
    sort_by: Literal["created_at", "invoice_date", "total_amount", "invoice_number"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def check_date_range(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


NonNegative = Annotated[Decimal, Field(ge=0)]


class LineItemInput(BaseModel):
    description: str = Field(min_length=1)
    hsn_code: str | None = Field(default=None, max_length=8)
    quantity: NonNegative | None = None
    unit_price: NonNegative | None = None
    tax_rate: Annotated[Decimal, Field(ge=0, le=100)] | None = None
    amount: NonNegative


class InvoiceUpdate(BaseModel):
    """Reviewer corrections (PATCH): only fields sent are changed; null clears a field."""

    model_config = ConfigDict(extra="forbid")

    vendor_name: str | None = Field(default=None, min_length=1, max_length=255)
    vendor_gstin: GSTIN | None = None
    invoice_number: str | None = Field(default=None, min_length=1, max_length=100)
    invoice_date: date | None = None
    subtotal: NonNegative | None = None
    cgst: NonNegative | None = None
    sgst: NonNegative | None = None
    igst: NonNegative | None = None
    total_amount: NonNegative | None = None
    line_items: list[LineItemInput] | None = None


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class VendorRead(VendorSummary):
    created_at: datetime
