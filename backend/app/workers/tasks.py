"""Celery tasks: thin wrappers that run the async pipeline."""

import asyncio
import logging
import random
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.integrations.factories import get_llm_provider, get_ocr_provider
from app.integrations.llm.base import LLMError
from app.integrations.storage.factory import get_storage
from app.schemas.extraction import ExtractedInvoice
from app.services.processing_service import InvoiceProcessor, ProcessingOutcome
from app.workers.celery_app import PROCESS_INVOICE_TASK, celery_app

logger = logging.getLogger(__name__)


def retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter: ~5s, 10s, 20s.

    Jitter (a random extra 0-1s) stops many invoices that failed together, e.g.
    during an LLM rate-limit window, from all retrying at the same instant.
    """
    return float(settings.RETRY_BACKOFF_SECONDS * 2**attempt + random.uniform(0, 1))


class _UnavailableLLM:
    """Stand-in when the LLM is misconfigured (e.g. no API key): the invoice is still
    claimed and then marked failed with a clear reason, instead of staying 'queued'."""

    def __init__(self, error: LLMError) -> None:
        self.error = error

    async def extract_invoice(self, ocr_text: str) -> ExtractedInvoice:
        raise self.error


async def _run_pipeline(invoice_id: uuid.UUID, attempt: int) -> ProcessingOutcome:
    # Each task runs in a fresh event loop (asyncio.run), and pooled DB connections
    # are bound to the loop that created them. NullPool opens a new connection per
    # task instead (cheap next to seconds of OCR) and avoids cross-loop errors.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        try:
            llm = get_llm_provider()
        except LLMError as exc:
            logger.error("LLM provider unavailable", extra={"error": str(exc)})
            llm = _UnavailableLLM(exc)
        processor = InvoiceProcessor(
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            storage=get_storage(),
            ocr=get_ocr_provider(),
            llm=llm,
        )
        return await processor.process(invoice_id, attempt)
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name=PROCESS_INVOICE_TASK,
    max_retries=settings.MAX_TASK_RETRIES,
    # Kill a task stuck far longer than any real invoice takes (e.g. a hung OCR call).
    soft_time_limit=300,
    time_limit=360,
)
def process_invoice(self, invoice_id: str) -> str:  # type: ignore[no-untyped-def]
    attempt = self.request.retries
    outcome = asyncio.run(_run_pipeline(uuid.UUID(invoice_id), attempt))
    if outcome == ProcessingOutcome.RETRY:
        # Raises celery.exceptions.Retry: the message is re-scheduled after the delay.
        raise self.retry(countdown=retry_delay(attempt))
    return outcome.value
