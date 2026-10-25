"""Invoice routes (upload, list, detail, status, file)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status

from app.api.deps import CurrentUser, DbSession, ReviewerUser
from app.core.config import settings
from app.core.rate_limit import limiter
from app.integrations.storage.base import StorageBackend
from app.integrations.storage.factory import get_storage
from app.models.invoice import Invoice
from app.schemas.common import Page
from app.schemas.invoice import (
    FileUrlResponse,
    InvoiceDetail,
    InvoiceListItem,
    InvoiceListQuery,
    InvoiceStatusRead,
    InvoiceUpdate,
    InvoiceUploadResponse,
    RejectRequest,
)
from app.services.invoice_service import InvoiceService
from app.services.review_service import ReviewService
from app.services.task_queue import TaskQueue, get_task_queue

router = APIRouter(prefix="/invoices", tags=["invoices"])


def get_invoice_service(
    db: DbSession,
    storage: Annotated[StorageBackend, Depends(get_storage)],
    tasks: Annotated[TaskQueue, Depends(get_task_queue)],
) -> InvoiceService:
    return InvoiceService(db, storage, tasks)


InvoiceServiceDep = Annotated[InvoiceService, Depends(get_invoice_service)]


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED, response_model=InvoiceUploadResponse)
@limiter.limit(settings.UPLOAD_RATE_LIMIT)
async def upload_invoice(
    request: Request,
    user: CurrentUser,
    service: InvoiceServiceDep,
    file: Annotated[UploadFile, File(description="PDF, JPG or PNG, max 10 MB")],
) -> Invoice:
    """202 Accepted: the file is stored and queued; processing happens in the background.
    Poll GET /invoices/{id}/status to follow progress."""
    # Read at most one byte over the limit: enough to detect "too large"
    # without holding a huge file in memory.
    data = await file.read(settings.max_upload_size_bytes + 1)
    return await service.upload(user, file.filename or "upload", data)


@router.get("")
async def list_invoices(
    user: CurrentUser,
    service: InvoiceServiceDep,
    query: Annotated[InvoiceListQuery, Query()],
) -> Page[InvoiceListItem]:
    return await service.list_invoices(user, query)


@router.get("/{invoice_id}", response_model=InvoiceDetail)
async def get_invoice(
    invoice_id: uuid.UUID, user: CurrentUser, service: InvoiceServiceDep
) -> Invoice:
    return await service.get_invoice(user, invoice_id)


@router.get("/{invoice_id}/status")
async def get_invoice_status(
    invoice_id: uuid.UUID, user: CurrentUser, service: InvoiceServiceDep
) -> InvoiceStatusRead:
    return await service.get_status(user, invoice_id)


@router.get("/{invoice_id}/file")
async def get_invoice_file(
    invoice_id: uuid.UUID, user: CurrentUser, service: InvoiceServiceDep
) -> FileUrlResponse:
    """Short-lived presigned URL to view the original document."""
    return await service.get_file_url(user, invoice_id)


@router.post("/{invoice_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_invoice(
    invoice_id: uuid.UUID, user: CurrentUser, service: InvoiceServiceDep
) -> InvoiceStatusRead:
    """Re-run processing for a failed invoice."""
    return await service.retry(user, invoice_id)


# ---------------------------------------------------------------- review (reviewer/admin)


def get_review_service(db: DbSession) -> ReviewService:
    return ReviewService(db)


ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]


@router.patch("/{invoice_id}", response_model=InvoiceDetail)
async def update_invoice(
    invoice_id: uuid.UUID, data: InvoiceUpdate, user: ReviewerUser, service: ReviewServiceDep
) -> Invoice:
    """Correct extracted fields. Validation re-runs; changes are audit-logged."""
    return await service.update(user, invoice_id, data)


@router.post("/{invoice_id}/approve", response_model=InvoiceUploadResponse)
async def approve_invoice(
    invoice_id: uuid.UUID, user: ReviewerUser, service: ReviewServiceDep
) -> Invoice:
    return await service.approve(user, invoice_id)


@router.post("/{invoice_id}/reject", response_model=InvoiceUploadResponse)
async def reject_invoice(
    invoice_id: uuid.UUID, data: RejectRequest, user: ReviewerUser, service: ReviewServiceDep
) -> Invoice:
    return await service.reject(user, invoice_id, data.reason)
