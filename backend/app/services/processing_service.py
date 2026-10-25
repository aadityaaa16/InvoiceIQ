"""The invoice processing pipeline, run by the Celery worker.

    queued --claim--> processing --download--> OCR --> LLM --> validate --> approved / needs_review
                          |                     |       |
                          |                OCRError  LLMRetryableError --> queued (retry)
                          |                     |       |   (after last retry) --> failed
                          +-- not claimable --> skip    LLMError -----------------> failed

Kept free of Celery so it can be tested directly. The task only translates the
returned outcome into "done" or "retry later".
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.llm.base import LLMError, LLMProvider, LLMRetryableError
from app.integrations.ocr.base import OCRError, OCRProvider
from app.integrations.storage.base import StorageBackend
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice, InvoiceLineItem
from app.repositories.audit_repository import AuditRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.vendor_repository import VendorRepository
from app.schemas.extraction import ExtractedInvoice
from app.services.invoice_rules import can_auto_approve, check_invoice
from app.services.validation import ValidationIssue
from app.utils.gstin import is_valid_gstin, normalize_gstin

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ProcessingOutcome(StrEnum):
    COMPLETED = "completed"  # extracted and validated: approved or needs_review
    SKIPPED = "skipped"  # not claimable: already processed or being processed
    RETRY = "retry"  # temporary failure; invoice re-queued, task should retry later
    FAILED = "failed"  # permanent failure; invoice marked failed


@contextmanager
def log_step(step: str, invoice_id: uuid.UUID) -> Iterator[None]:
    """Log how long each pipeline step takes, tagged with the invoice id."""
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.info(
            "pipeline step finished",
            extra={
                "invoice_id": str(invoice_id),
                "step": step,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )


class InvoiceProcessor:
    def __init__(
        self,
        session_factory: SessionFactory,
        storage: StorageBackend,
        ocr: OCRProvider,
        llm: LLMProvider,
        max_retries: int = settings.MAX_TASK_RETRIES,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.ocr = ocr
        self.llm = llm
        self.max_retries = max_retries

    async def process(self, invoice_id: uuid.UUID, attempt: int = 0) -> ProcessingOutcome:
        """attempt: 0 for the first run, 1..max_retries for retries."""
        async with self.session_factory() as session:
            with log_step("total", invoice_id):
                return await self._process(session, invoice_id, attempt)

    async def _process(
        self, session: AsyncSession, invoice_id: uuid.UUID, attempt: int
    ) -> ProcessingOutcome:
        invoices = InvoiceRepository(session)

        # Step 1: idempotency. Claim the invoice atomically, or exit.
        stale_before = datetime.now(UTC) - timedelta(
            seconds=settings.PROCESSING_STALE_AFTER_SECONDS
        )
        invoice = await invoices.claim_for_processing(invoice_id, stale_before)
        if invoice is None:
            logger.info("Invoice not claimable, skipping", extra={"invoice_id": str(invoice_id)})
            return ProcessingOutcome.SKIPPED
        await session.commit()  # make "processing" visible to the API right away

        try:
            # Step 2: download + OCR
            with log_step("download", invoice_id):
                data = await self.storage.download(invoice.file_key)
            with log_step("ocr", invoice_id):
                # OCR is CPU-bound and synchronous; run it in a thread.
                text = await asyncio.to_thread(self.ocr.extract_text, data, invoice.file_type)
            invoice.raw_ocr_text = text  # kept even if the LLM step fails (debugging)

            # Step 3: LLM structured extraction
            with log_step("llm", invoice_id):
                extracted = await self.llm.extract_invoice(text)

        except OCRError as exc:
            return await self._fail(session, invoice, f"OCR failed: {exc}")
        except LLMRetryableError as exc:
            # Step 4: temporary failure. Re-queue for another attempt, or give up.
            if attempt < self.max_retries:
                invoice.status = InvoiceStatus.QUEUED
                invoice.retry_count = attempt + 1
                invoice.failure_reason = f"Attempt {attempt + 1} failed, will retry: {exc}"
                await session.commit()
                logger.warning(
                    "Retryable extraction error",
                    extra={"invoice_id": str(invoice.id), "attempt": attempt, "error": str(exc)},
                )
                return ProcessingOutcome.RETRY
            return await self._fail(
                session, invoice, f"Extraction failed after {attempt + 1} attempts: {exc}"
            )
        except LLMError as exc:
            return await self._fail(session, invoice, f"Extraction failed: {exc}")
        except Exception:
            # Unexpected bug or outage: never leave the invoice stuck in "processing".
            logger.exception("Unexpected pipeline error", extra={"invoice_id": str(invoice.id)})
            return await self._fail(session, invoice, "Unexpected processing error")

        self._apply_extraction(invoice, extracted)
        invoice.failure_reason = None
        invoice.processed_at = datetime.now(UTC)
        with log_step("validate", invoice_id):
            await self._validate_and_decide(session, invoice, extracted)
        await session.commit()
        logger.info(
            "Invoice processed",
            extra={
                "invoice_id": str(invoice.id),
                "status": invoice.status,
                "confidence": invoice.confidence_score,
                "issues": len(invoice.validation_errors or []),
            },
        )
        return ProcessingOutcome.COMPLETED

    async def _validate_and_decide(
        self, session: AsyncSession, invoice: Invoice, extracted: ExtractedInvoice
    ) -> None:
        """Steps 5-7: vendor matching, rule-based validation, auto-approve or review."""
        gstin = normalize_gstin(extracted.vendor_gstin) if extracted.vendor_gstin else None
        # Step 6: only a GSTIN that passes the checksum becomes a vendor. A misread one
        # would otherwise create a bogus vendor for every OCR error.
        if gstin and is_valid_gstin(gstin):
            vendor = await VendorRepository(session).get_or_create(
                invoice.organization_id, gstin, extracted.vendor_name or gstin
            )
            invoice.vendor_id = vendor.id
        await session.flush()

        # Step 5: business rules + duplicate check.
        issues = await check_invoice(session, invoice, gstin)
        invoice.validation_errors = [issue.to_dict() for issue in issues]

        # Step 7: decide.
        if not can_auto_approve(issues, invoice.confidence_score):
            invoice.status = InvoiceStatus.NEEDS_REVIEW
            return
        try:
            # SAVEPOINT: if the partial unique index rejects the approval (a duplicate
            # approved concurrently by another worker), only this step is undone.
            async with session.begin_nested():
                invoice.status = InvoiceStatus.APPROVED
                invoice.approved_at = datetime.now(UTC)
                await session.flush()
        except IntegrityError:
            await session.refresh(invoice)
            invoice.status = InvoiceStatus.NEEDS_REVIEW
            invoice.validation_errors = [
                ValidationIssue(
                    "possible_duplicate", "invoice_number", "A matching invoice was just approved"
                ).to_dict()
            ]
            return
        await AuditRepository(session).record(
            organization_id=invoice.organization_id,
            user_id=None,  # system action
            entity_id=invoice.id,
            action="auto_approve",
            new_values={"status": "approved", "confidence": invoice.confidence_score},
        )

    @staticmethod
    def _apply_extraction(invoice: Invoice, extracted: ExtractedInvoice) -> None:
        invoice.invoice_number = extracted.invoice_number
        invoice.invoice_date = extracted.invoice_date
        invoice.subtotal = extracted.subtotal
        invoice.cgst = extracted.cgst
        invoice.sgst = extracted.sgst
        invoice.igst = extracted.igst
        invoice.total_amount = extracted.total_amount
        invoice.confidence_score = extracted.overall_confidence()
        invoice.raw_llm_output = extracted.model_dump(mode="json")
        # Replace, not append: re-processing the same invoice gives the same result.
        invoice.line_items = [InvoiceLineItem(**item.model_dump()) for item in extracted.line_items]

    @staticmethod
    async def _fail(session: AsyncSession, invoice: Invoice, reason: str) -> ProcessingOutcome:
        invoice.status = InvoiceStatus.FAILED
        invoice.failure_reason = reason
        await session.commit()
        logger.warning("Invoice failed", extra={"invoice_id": str(invoice.id), "reason": reason})
        return ProcessingOutcome.FAILED
