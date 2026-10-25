"""GSTR-2B reconciliation and dashboard routes."""

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import CurrentUser, DbSession, ReviewerUser
from app.integrations.storage.base import StorageBackend
from app.integrations.storage.factory import get_storage
from app.models.enums import MatchStatus
from app.models.reconciliation import ReconciliationResult, ReconciliationRun
from app.schemas.reconciliation import (
    PERIOD_PATTERN,
    DashboardStats,
    ReconciliationResultRead,
    ReconciliationRunRead,
)
from app.services.dashboard_service import DashboardService
from app.services.reconciliation_service import MAX_GSTR_FILE_BYTES, ReconciliationService

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_reconciliation_service(
    db: DbSession, storage: Annotated[StorageBackend, Depends(get_storage)]
) -> ReconciliationService:
    return ReconciliationService(db, storage)


ServiceDep = Annotated[ReconciliationService, Depends(get_reconciliation_service)]


@router.post("/runs", status_code=status.HTTP_201_CREATED, response_model=ReconciliationRunRead)
async def create_run(
    user: ReviewerUser,
    service: ServiceDep,
    period: Annotated[str, Form(pattern=PERIOD_PATTERN, description="Tax period, YYYY-MM")],
    file: Annotated[UploadFile, File(description="GSTR-2B as .json (portal) or .xlsx")],
) -> ReconciliationRun:
    data = await file.read(MAX_GSTR_FILE_BYTES + 1)
    return await service.create_run(user, period, file.filename or "gstr2b", data)


@router.get("/runs", response_model=list[ReconciliationRunRead])
async def list_runs(user: CurrentUser, service: ServiceDep) -> Sequence[ReconciliationRun]:
    return await service.list_runs(user)


@router.get("/runs/{run_id}/results", response_model=list[ReconciliationResultRead])
async def list_results(
    run_id: uuid.UUID,
    user: CurrentUser,
    service: ServiceDep,
    match_status: MatchStatus | None = None,
) -> Sequence[ReconciliationResult]:
    return await service.list_results(user, run_id, match_status)


@dashboard_router.get("/stats")
async def dashboard_stats(user: CurrentUser, db: DbSession) -> DashboardStats:
    return await DashboardService(db).stats(user)
