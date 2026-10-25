import asyncio
import calendar
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.integrations.storage.base import StorageBackend
from app.models.enums import MatchStatus, ReconciliationStatus
from app.models.reconciliation import ReconciliationResult, ReconciliationRun
from app.models.user import User
from app.repositories.reconciliation_repository import ReconciliationRepository
from app.services.gstr2b_parser import parse_gstr2b
from app.services.reconciliation import BookEntry, reconcile, summarize
from app.utils.files import sanitize_filename

MAX_GSTR_FILE_BYTES = 20 * 1024 * 1024
ZERO = Decimal("0")


def period_bounds(period: str) -> tuple[date, date]:
    """'2026-09' -> (2026-09-01, 2026-09-30)."""
    year, month = int(period[:4]), int(period[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


class ReconciliationService:
    def __init__(self, session: AsyncSession, storage: StorageBackend) -> None:
        self.session = session
        self.storage = storage
        self.repo = ReconciliationRepository(session)

    async def create_run(
        self, user: User, period: str, filename: str, data: bytes
    ) -> ReconciliationRun:
        if not data:
            raise BadRequestError("The uploaded file is empty")
        if len(data) > MAX_GSTR_FILE_BYTES:
            raise BadRequestError("GSTR-2B file is too large (max 20 MB)")
        # Parse before storing anything: a bad file fails fast with a clear 400.
        # Parsing is CPU work (Excel especially), so keep it off the event loop.
        records = await asyncio.to_thread(parse_gstr2b, filename, data)

        run_id = uuid.uuid4()
        extension = "json" if filename.lower().endswith(".json") else "xlsx"
        file_key = f"{user.organization_id}/gstr2b/{period}/{run_id}.{extension}"
        await self.storage.upload(file_key, data, "application/octet-stream")

        start, end = period_bounds(period)
        invoices = await self.repo.approved_invoices_between(user.organization_id, start, end)
        books = [
            BookEntry(
                invoice_id=invoice.id,
                vendor_gstin=invoice.vendor.gstin,
                invoice_number=invoice.invoice_number or "",
                total_amount=invoice.total_amount or ZERO,
                total_tax=(invoice.cgst or ZERO) + (invoice.sgst or ZERO) + (invoice.igst or ZERO),
            )
            for invoice in invoices
            if invoice.vendor is not None
        ]
        results = reconcile(books, records, settings.AMOUNT_TOLERANCE)

        run = await self.repo.add_run(
            ReconciliationRun(
                id=run_id,
                organization_id=user.organization_id,
                period=period,
                file_key=file_key,
                status=ReconciliationStatus.COMPLETED,
                summary={**summarize(results, books), "file": sanitize_filename(filename)},
                created_by=user.id,
            )
        )
        self.session.add_all(
            ReconciliationResult(
                run_id=run.id,
                invoice_id=result.invoice_id,
                gstr_record=result.gstr_record.model_dump(mode="json")
                if result.gstr_record
                else None,
                match_status=result.status,
                difference_amount=result.difference,
            )
            for result in results
        )
        # Run and all its results commit together (one transaction).
        await self.session.commit()
        return run

    async def list_runs(self, user: User) -> Sequence[ReconciliationRun]:
        return await self.repo.list_runs(user.organization_id)

    async def list_results(
        self, user: User, run_id: uuid.UUID, match_status: MatchStatus | None
    ) -> Sequence[ReconciliationResult]:
        if await self.repo.get_run(user.organization_id, run_id) is None:
            raise NotFoundError("Reconciliation run not found")
        return await self.repo.list_results(run_id, match_status)
