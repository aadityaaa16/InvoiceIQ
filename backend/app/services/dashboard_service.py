"""Dashboard stats: a few aggregate queries, computed in the database (not in Python)."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice
from app.models.user import User
from app.schemas.reconciliation import DashboardStats

# Invoices whose extraction finished (a decision was made, automatic or human).
_PROCESSED = [InvoiceStatus.APPROVED, InvoiceStatus.NEEDS_REVIEW, InvoiceStatus.REJECTED]


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def stats(self, user: User) -> DashboardStats:
        org = user.organization_id

        # GROUP BY in SQL: one row per status, instead of loading every invoice.
        rows = await self.session.execute(
            select(Invoice.status, func.count())
            .where(Invoice.organization_id == org)
            .group_by(Invoice.status)
        )
        counts = {status: 0 for status in InvoiceStatus} | {status: n for status, n in rows.all()}
        processed = sum(counts[status] for status in _PROCESSED)

        auto_approved = (
            await self.session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.organization_id == org, AuditLog.action == "auto_approve")
            )
            or 0
        )

        avg_seconds = await self.session.scalar(
            select(func.avg(extract("epoch", Invoice.processed_at - Invoice.created_at))).where(
                Invoice.organization_id == org, Invoice.processed_at.is_not(None)
            )
        )

        month_start = datetime.now(UTC).date().replace(day=1)
        approved_amount = await self.session.scalar(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.organization_id == org,
                Invoice.status == InvoiceStatus.APPROVED,
                Invoice.invoice_date >= month_start,
            )
        )

        return DashboardStats(
            total_invoices=sum(counts.values()),
            counts_by_status=counts,
            auto_approval_rate=round(auto_approved / processed, 3) if processed else None,
            avg_processing_seconds=round(float(avg_seconds), 1)
            if avg_seconds is not None
            else None,
            approved_amount_this_month=Decimal(approved_amount or 0),
        )
