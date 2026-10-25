"""Insert test rows directly, for states the API cannot create yet (e.g. extracted data)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice, InvoiceLineItem
from app.models.vendor import Vendor


async def make_vendor(
    session: AsyncSession, organization_id: uuid.UUID, name: str = "Sharma Distributors"
) -> Vendor:
    vendor = Vendor(organization_id=organization_id, name=name, gstin="27AAPFU0939F1ZV")
    session.add(vendor)
    await session.flush()
    return vendor


async def make_invoice(
    session: AsyncSession,
    organization_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    *,
    line_items: list[dict[str, Any]] | None = None,
    **fields: Any,
) -> Invoice:
    defaults: dict[str, Any] = {
        "file_key": f"{organization_id}/invoices/{uuid.uuid4()}/original.pdf",
        "original_filename": "invoice.pdf",
        "file_type": "pdf",
        "status": InvoiceStatus.NEEDS_REVIEW,
        "invoice_number": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": date(2026, 9, 15),
        "total_amount": Decimal("1180.00"),
    }
    invoice = Invoice(
        organization_id=organization_id, uploaded_by=uploaded_by, **(defaults | fields)
    )
    invoice.line_items = [InvoiceLineItem(**item) for item in line_items or []]
    session.add(invoice)
    await session.flush()
    return invoice
