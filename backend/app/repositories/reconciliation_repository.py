import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import InvoiceStatus, MatchStatus
from app.models.invoice import Invoice
from app.models.reconciliation import ReconciliationResult, ReconciliationRun


class ReconciliationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def approved_invoices_between(
        self, organization_id: uuid.UUID, start: date, end: date
    ) -> Sequence[Invoice]:
        result = await self.session.execute(
            select(Invoice)
            .options(selectinload(Invoice.vendor))
            .where(
                Invoice.organization_id == organization_id,
                Invoice.status == InvoiceStatus.APPROVED,
                Invoice.vendor_id.is_not(None),
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
        )
        return result.scalars().all()

    async def add_run(self, run: ReconciliationRun) -> ReconciliationRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def list_runs(self, organization_id: uuid.UUID) -> Sequence[ReconciliationRun]:
        result = await self.session.execute(
            select(ReconciliationRun)
            .where(ReconciliationRun.organization_id == organization_id)
            .order_by(ReconciliationRun.created_at.desc())
        )
        return result.scalars().all()

    async def get_run(
        self, organization_id: uuid.UUID, run_id: uuid.UUID
    ) -> ReconciliationRun | None:
        result = await self.session.execute(
            select(ReconciliationRun).where(
                ReconciliationRun.id == run_id,
                ReconciliationRun.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_results(
        self, run_id: uuid.UUID, match_status: MatchStatus | None
    ) -> Sequence[ReconciliationResult]:
        query = select(ReconciliationResult).where(ReconciliationResult.run_id == run_id)
        if match_status:
            query = query.where(ReconciliationResult.match_status == match_status)
        result = await self.session.execute(query.order_by(ReconciliationResult.match_status))
        return result.scalars().all()
