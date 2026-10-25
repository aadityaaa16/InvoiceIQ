import logging
import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedFileTypeError,
)
from app.integrations.storage.base import StorageBackend
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice
from app.models.user import User
from app.repositories.invoice_repository import InvoiceRepository
from app.schemas.common import Page
from app.schemas.invoice import (
    FileUrlResponse,
    InvoiceListItem,
    InvoiceListQuery,
    InvoiceStatusRead,
)
from app.services.task_queue import TaskQueue
from app.utils.files import CONTENT_TYPES, detect_file_type, sanitize_filename

logger = logging.getLogger(__name__)


class InvoiceService:
    def __init__(self, session: AsyncSession, storage: StorageBackend, tasks: TaskQueue) -> None:
        self.session = session
        self.storage = storage
        self.tasks = tasks
        self.invoices = InvoiceRepository(session)

    async def upload(self, user: User, filename: str, data: bytes) -> Invoice:
        """Validate, store the file, create the invoice row, then enqueue processing."""
        if not data:
            raise BadRequestError("The uploaded file is empty")
        if len(data) > settings.max_upload_size_bytes:
            raise PayloadTooLargeError(f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB")
        file_type = detect_file_type(data)
        if file_type is None:
            raise UnsupportedFileTypeError("Only PDF, JPG and PNG files are supported")

        invoice_id = uuid.uuid4()
        # Key starts with the organization id: tenants' files are separated by prefix,
        # and the original filename is never part of the key (no path tricks, no clashes).
        file_key = f"{user.organization_id}/invoices/{invoice_id}/original.{file_type}"

        # 1. Upload first: if it fails, nothing was written to the DB.
        await self.storage.upload(file_key, data, CONTENT_TYPES[file_type])

        # 2. Then the DB row. If the commit fails, remove the now-orphaned file.
        invoice = Invoice(
            id=invoice_id,
            organization_id=user.organization_id,
            uploaded_by=user.id,
            file_key=file_key,
            original_filename=sanitize_filename(filename),
            file_type=file_type,
            status=InvoiceStatus.QUEUED,
        )
        try:
            await self.invoices.add(invoice)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            await self.storage.delete(file_key)
            raise

        # 3. Enqueue only AFTER commit, or the worker could look for a row that is
        #    not visible yet. If the broker is down, mark the invoice failed so the
        #    user can retry it, instead of leaving it "queued" forever.
        try:
            await self.tasks.enqueue_invoice_processing(invoice.id)
        except Exception:
            logger.exception("Failed to enqueue invoice", extra={"invoice_id": str(invoice.id)})
            invoice.status = InvoiceStatus.FAILED
            invoice.failure_reason = "Could not queue the invoice for processing; please retry"
            await self.session.commit()

        logger.info(
            "Invoice uploaded",
            extra={"invoice_id": str(invoice.id), "file_type": file_type, "size": len(data)},
        )
        return invoice

    async def list_invoices(self, user: User, query: InvoiceListQuery) -> Page[InvoiceListItem]:
        items, total = await self.invoices.list(user.organization_id, query)
        return Page[InvoiceListItem](
            items=[InvoiceListItem.model_validate(item) for item in items],
            total=total,
            page=query.page,
            page_size=query.page_size,
            pages=math.ceil(total / query.page_size) if total else 0,
        )

    async def get_invoice(self, user: User, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self.invoices.get_with_details(user.organization_id, invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        return invoice

    async def get_status(self, user: User, invoice_id: uuid.UUID) -> InvoiceStatusRead:
        row = await self.invoices.get_status(user.organization_id, invoice_id)
        if row is None:
            raise NotFoundError("Invoice not found")
        return InvoiceStatusRead.model_validate(row)

    async def get_file_url(self, user: User, invoice_id: uuid.UUID) -> FileUrlResponse:
        invoice = await self.invoices.get(user.organization_id, invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        # The bucket stays private; the browser gets a short-lived signed link instead.
        expires_in = settings.PRESIGNED_URL_EXPIRE_SECONDS
        url = await self.storage.presigned_url(invoice.file_key, expires_in)
        return FileUrlResponse(url=url, expires_in=expires_in)
