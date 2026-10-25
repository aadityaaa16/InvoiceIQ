import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Row, and_, func, or_, select, update
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

    async def claim_for_processing(
        self, invoice_id: uuid.UUID, stale_before: datetime
    ) -> Invoice | None:
        """Atomically move an invoice to 'processing'. Returns None if it is not claimable.

        This single UPDATE ... WHERE status = 'queued' is a compare-and-set: if the same
        task is delivered twice, both workers run it, but Postgres row locking lets only
        ONE of them match the WHERE clause. The other gets no row and exits. That is
        what makes processing idempotent (an invoice is never processed twice at once).

        A 'processing' invoice not updated since `stale_before` belonged to a worker that
        crashed mid-task, so it may be claimed again instead of being stuck forever.
        """
        claimed = await self.session.execute(
            update(Invoice)
            .where(
                Invoice.id == invoice_id,
                or_(
                    Invoice.status == InvoiceStatus.QUEUED,
                    and_(
                        Invoice.status == InvoiceStatus.PROCESSING,
                        Invoice.updated_at < stale_before,
                    ),
                ),
            )
            .values(status=InvoiceStatus.PROCESSING, updated_at=func.now())
            .returning(Invoice.id)
        )
        if claimed.scalar_one_or_none() is None:
            return None
        result = await self.session.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(Invoice.id == invoice_id)
            # Refresh any copy already in this session with the values just written.
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def requeue_failed(self, organization_id: uuid.UUID, invoice_id: uuid.UUID) -> bool:
        """Atomically move a FAILED invoice back to 'queued'. False if it was not failed."""
        result = await self.session.execute(
            update(Invoice)
            .where(
                Invoice.id == invoice_id,
                Invoice.organization_id == organization_id,
                Invoice.status == InvoiceStatus.FAILED,
            )
            .values(
                status=InvoiceStatus.QUEUED,
                failure_reason=None,
                retry_count=0,
                updated_at=func.now(),
            )
            .returning(Invoice.id)
        )
        return result.scalar_one_or_none() is not None
