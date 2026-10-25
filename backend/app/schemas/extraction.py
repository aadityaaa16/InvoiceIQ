"""The structured output we ask the LLM for, and validate it against.

This schema is sent to the LLM as a JSON Schema (structured output), and the
response is parsed back through the same model, so anything malformed is
rejected here instead of reaching the database.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, WithJsonSchema

# The LLM sees a plain JSON number; Pydantic parses that number straight into an
# exact Decimal (from its digits, never via float arithmetic).
Amount = Annotated[Decimal, WithJsonSchema({"type": "number"})]

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class ExtractedLineItem(BaseModel):
    description: str
    hsn_code: str | None = Field(default=None, description="HSN/SAC code if printed")
    quantity: Amount | None = None
    unit_price: Amount | None = None
    tax_rate: Amount | None = Field(default=None, description="GST rate in percent, e.g. 18")
    amount: Amount = Field(description="Line amount before tax")


class FieldConfidence(BaseModel):
    """The model's own 0-1 confidence per field group."""

    vendor_name: Confidence
    vendor_gstin: Confidence
    invoice_number: Confidence
    invoice_date: Confidence
    line_items: Confidence
    totals: Confidence


class ExtractedInvoice(BaseModel):
    vendor_name: str | None = Field(description="Name of the SUPPLIER who issued the invoice")
    vendor_gstin: str | None = Field(description="15-character GSTIN of the SUPPLIER")
    invoice_number: str | None
    invoice_date: date | None = Field(description="ISO date, YYYY-MM-DD")
    line_items: list[ExtractedLineItem]
    subtotal: Amount | None = Field(description="Taxable value: total before taxes")
    cgst: Amount | None = None
    sgst: Amount | None = None
    igst: Amount | None = None
    total_amount: Amount | None = Field(description="Grand total including taxes")
    confidence: FieldConfidence

    def overall_confidence(self) -> float:
        """Weakest-link score: an invoice is only as reliable as its least certain field."""
        c = self.confidence
        return min(
            c.vendor_name, c.vendor_gstin, c.invoice_number, c.invoice_date, c.line_items, c.totals
        )
