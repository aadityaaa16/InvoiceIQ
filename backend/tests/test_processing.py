"""Pipeline tests with mocked OCR and LLM (no Celery, no network)."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm.base import LLMError, LLMRetryableError
from app.integrations.ocr.base import OCRError
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice
from app.models.organization import Organization
from app.models.user import User
from app.services.processing_service import InvoiceProcessor, ProcessingOutcome
from app.workers.tasks import retry_delay
from tests.factories import make_invoice
from tests.fakes import FakeLLM, FakeOCR, FakeStorage, sample_extraction

PDF = b"%PDF-1.7 test"


@pytest.fixture
async def queued_invoice(db_session: AsyncSession, storage: FakeStorage) -> Invoice:
    org = Organization(name="Acme")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        email=f"{uuid.uuid4().hex}@acme.com",
        hashed_password="x",
        full_name="U",
        role="uploader",
    )
    db_session.add(user)
    await db_session.flush()
    invoice = await make_invoice(
        db_session,
        org.id,
        user.id,
        status=InvoiceStatus.QUEUED,
        invoice_number=None,
        invoice_date=None,
        total_amount=None,
    )
    await storage.upload(invoice.file_key, PDF, "application/pdf")
    return invoice


def make_processor(
    db_session: AsyncSession, storage: FakeStorage, ocr: FakeOCR, llm: FakeLLM
) -> InvoiceProcessor:
    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        yield db_session  # reuse the test's rolled-back session

    return InvoiceProcessor(session_factory, storage, ocr, llm, max_retries=3)


async def test_happy_path_extracts_and_stores_everything(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    ocr, llm = FakeOCR(), FakeLLM()
    outcome = await make_processor(db_session, storage, ocr, llm).process(queued_invoice.id)

    assert outcome == ProcessingOutcome.COMPLETED
    invoice = queued_invoice
    assert invoice.status == InvoiceStatus.APPROVED  # clean + confident -> auto-approved
    assert invoice.validation_errors == []
    assert invoice.vendor_id is not None
    assert invoice.invoice_number == "INV-001"
    assert invoice.total_amount == Decimal("1180")
    assert invoice.cgst == invoice.sgst == Decimal("90")
    assert invoice.raw_ocr_text == ocr.text
    assert invoice.raw_llm_output is not None
    assert invoice.raw_llm_output["vendor_gstin"] == "27AAPFU0939F1ZV"
    assert invoice.confidence_score == pytest.approx(0.92)  # weakest field
    assert [item.description for item in invoice.line_items] == ["Steel rods", "Binding wire"]
    assert llm.prompts == [ocr.text]  # the LLM received the OCR output


@pytest.mark.parametrize(
    "status", [InvoiceStatus.APPROVED, InvoiceStatus.NEEDS_REVIEW, InvoiceStatus.PROCESSING]
)
async def test_not_claimable_invoice_is_skipped(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice, status: InvoiceStatus
) -> None:
    """Idempotency: a duplicate task delivery must not process the invoice again."""
    queued_invoice.status = status
    await db_session.flush()
    ocr = FakeOCR()

    outcome = await make_processor(db_session, storage, ocr, FakeLLM()).process(queued_invoice.id)

    assert outcome == ProcessingOutcome.SKIPPED
    assert ocr.calls == 0  # no work was done


async def test_second_delivery_of_same_task_is_skipped(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    ocr = FakeOCR()
    processor = make_processor(db_session, storage, ocr, FakeLLM())
    assert await processor.process(queued_invoice.id) == ProcessingOutcome.COMPLETED
    assert await processor.process(queued_invoice.id) == ProcessingOutcome.SKIPPED
    assert ocr.calls == 1


async def test_stale_processing_invoice_is_reclaimed(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    """A worker crashed mid-task long ago: the invoice must not stay stuck."""
    queued_invoice.status = InvoiceStatus.PROCESSING
    queued_invoice.updated_at = datetime(2020, 1, 1, tzinfo=UTC)
    await db_session.flush()

    outcome = await make_processor(db_session, storage, FakeOCR(), FakeLLM()).process(
        queued_invoice.id
    )
    assert outcome == ProcessingOutcome.COMPLETED


async def test_retryable_llm_error_requeues_invoice(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    llm = FakeLLM(LLMRetryableError("rate limited"))
    outcome = await make_processor(db_session, storage, FakeOCR(), llm).process(
        queued_invoice.id, attempt=0
    )

    assert outcome == ProcessingOutcome.RETRY
    assert queued_invoice.status == InvoiceStatus.QUEUED  # claimable again by the retry
    assert queued_invoice.retry_count == 1
    assert queued_invoice.raw_ocr_text  # OCR result kept


async def test_retry_then_success(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    llm = FakeLLM(LLMRetryableError("timeout"), sample_extraction())
    processor = make_processor(db_session, storage, FakeOCR(), llm)

    assert await processor.process(queued_invoice.id, attempt=0) == ProcessingOutcome.RETRY
    assert await processor.process(queued_invoice.id, attempt=1) == ProcessingOutcome.COMPLETED
    assert queued_invoice.status == InvoiceStatus.APPROVED
    assert queued_invoice.failure_reason is None


async def test_retryable_error_on_last_attempt_fails(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    llm = FakeLLM(LLMRetryableError("invalid JSON"))
    outcome = await make_processor(db_session, storage, FakeOCR(), llm).process(
        queued_invoice.id, attempt=3
    )

    assert outcome == ProcessingOutcome.FAILED
    assert queued_invoice.status == InvoiceStatus.FAILED
    assert queued_invoice.failure_reason is not None
    assert "after 4 attempts" in queued_invoice.failure_reason


async def test_permanent_llm_error_fails_without_retry(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    llm = FakeLLM(LLMError("invalid API key"))
    outcome = await make_processor(db_session, storage, FakeOCR(), llm).process(
        queued_invoice.id, attempt=0
    )
    assert outcome == ProcessingOutcome.FAILED
    assert queued_invoice.failure_reason == "Extraction failed: invalid API key"


async def test_ocr_error_fails_without_calling_llm(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    ocr, llm = FakeOCR(), FakeLLM()
    ocr.error = OCRError("No readable text found")
    outcome = await make_processor(db_session, storage, ocr, llm).process(queued_invoice.id)

    assert outcome == ProcessingOutcome.FAILED
    assert queued_invoice.failure_reason == "OCR failed: No readable text found"
    assert llm.prompts == []


async def test_unexpected_error_never_leaves_invoice_processing(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    storage.objects.clear()  # download will raise KeyError
    outcome = await make_processor(db_session, storage, FakeOCR(), FakeLLM()).process(
        queued_invoice.id
    )
    assert outcome == ProcessingOutcome.FAILED
    assert queued_invoice.status == InvoiceStatus.FAILED


async def test_reprocessing_replaces_line_items(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    processor = make_processor(db_session, storage, FakeOCR(), FakeLLM())
    await processor.process(queued_invoice.id)
    queued_invoice.status = InvoiceStatus.QUEUED  # e.g. manual retry
    await db_session.flush()
    await processor.process(queued_invoice.id)
    assert len(queued_invoice.line_items) == 2  # not 4


def test_retry_delay_grows_exponentially() -> None:
    delays = [retry_delay(attempt) for attempt in range(3)]
    assert 5 <= delays[0] < 6
    assert 10 <= delays[1] < 11
    assert 20 <= delays[2] < 21


# ---------------------------------------------------------------- Phase 5: decisions


async def _process_with(
    db_session: AsyncSession, storage: FakeStorage, invoice: Invoice, **overrides: object
) -> Invoice:
    llm = FakeLLM(sample_extraction(**overrides))
    await make_processor(db_session, storage, FakeOCR(), llm).process(invoice.id)
    return invoice


def _codes(invoice: Invoice) -> list[str]:
    return [error["code"] for error in invoice.validation_errors or []]


async def test_low_confidence_goes_to_review(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    confidence = sample_extraction().confidence.model_dump() | {"totals": 0.5}
    invoice = await _process_with(db_session, storage, queued_invoice, confidence=confidence)
    assert invoice.status == InvoiceStatus.NEEDS_REVIEW
    assert invoice.validation_errors == []  # rules pass; only confidence is too low


async def test_rule_violation_goes_to_review_with_errors(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    invoice = await _process_with(db_session, storage, queued_invoice, total_amount=2000)
    assert invoice.status == InvoiceStatus.NEEDS_REVIEW
    assert _codes(invoice) == ["total_mismatch"]


async def test_bad_gstin_checksum_creates_no_vendor(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    invoice = await _process_with(
        db_session, storage, queued_invoice, vendor_gstin="27AAPFU0939F1ZX"
    )
    assert invoice.vendor_id is None
    assert invoice.status == InvoiceStatus.NEEDS_REVIEW
    assert "invalid_gstin" in _codes(invoice)


async def test_duplicate_invoice_is_flagged_not_approved(
    db_session: AsyncSession, storage: FakeStorage, queued_invoice: Invoice
) -> None:
    first = await _process_with(db_session, storage, queued_invoice)
    assert first.status == InvoiceStatus.APPROVED

    second = await make_invoice(
        db_session,
        first.organization_id,
        first.uploaded_by,
        status=InvoiceStatus.QUEUED,
        invoice_number=None,
        total_amount=None,
    )
    await storage.upload(second.file_key, PDF, "application/pdf")
    await _process_with(db_session, storage, second)

    assert second.vendor_id == first.vendor_id  # same GSTIN -> same vendor reused
    assert second.status == InvoiceStatus.NEEDS_REVIEW
    assert _codes(second) == ["possible_duplicate"]
