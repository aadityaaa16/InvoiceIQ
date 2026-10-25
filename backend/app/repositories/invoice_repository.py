import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice
from app.schemas.invoice import InvoiceListQuery

_SORT_COLUMNS = {
    "created_at": Invoice.created_at,
    "invoice_date": Invoice.invoice_date,
    "total_amount": Invoice.total_amount,
    "invoice_number": Invoice.invoice_number,
}


class InvoiceRepository:
    """Every query takes organization_id: tenant scoping is not optional."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, invoice: Invoice) -> Invoice:
        self.session.add(invoice)
        await self.session.flush()
        return invoice

    async def get(self, organization_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice | None:
        result = await self.session.execute(
            select(Invoice).where(
                Invoice.id == invoice_id, Invoice.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()

    async def get_with_details(
        self, organization_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> Invoice | None:
        # selectinload: one extra query per relationship ("SELECT ... WHERE invoice_id IN"),
        # instead of one query per line item (the N+1 problem).
        result = await self.session.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items), selectinload(Invoice.vendor))
            .where(Invoice.id == invoice_id, Invoice.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def get_status(
        self, organization_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> Row[uuid.UUID, InvoiceStatus, str | None, datetime] | None:
        # Selects only 4 columns, not the whole row (which includes large OCR text):
        # this endpoint is polled every few seconds by every open browser tab.
        result = await self.session.execute(
            select(Invoice.id, Invoice.status, Invoice.failure_reason, Invoice.updated_at).where(
                Invoice.id == invoice_id, Invoice.organization_id == organization_id
            )
        )
        return result.one_or_none()

    async def list(
        self, organization_id: uuid.UUID, query: InvoiceListQuery
    ) -> tuple[Sequence[Invoice], int]:
        conditions = [Invoice.organization_id == organization_id]
        if query.status:
            conditions.append(Invoice.status.in_(query.status))
        if query.vendor_id:
            conditions.append(Invoice.vendor_id == query.vendor_id)
        if query.date_from:
            conditions.append(Invoice.invoice_date >= query.date_from)
        if query.date_to:
            conditions.append(Invoice.invoice_date <= query.date_to)

        total = await self.session.scalar(
            select(func.count()).select_from(Invoice).where(*conditions)
        )

        column = _SORT_COLUMNS[query.sort_by]
        order = column.asc() if query.sort_order == "asc" else column.desc()
        result = await self.session.execute(
            select(Invoice)
            .options(selectinload(Invoice.vendor))
            .where(*conditions)
            # NULLs last (unprocessed invoices have no amount yet); Invoice.id as a
            # tie-breaker gives a stable order, so rows don't jump between pages.
            .order_by(order.nulls_last(), Invoice.id)
            .limit(query.page_size)
            .offset((query.page - 1) * query.page_size)
        )
        return result.scalars().all(), total or 0
