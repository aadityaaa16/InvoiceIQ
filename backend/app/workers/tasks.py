"""Celery tasks. The processing pipeline itself is implemented in Phase 4."""

import logging

from app.workers.celery_app import PROCESS_INVOICE_TASK, celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name=PROCESS_INVOICE_TASK)
def process_invoice(invoice_id: str) -> None:
    logger.info("Invoice processing not implemented yet", extra={"invoice_id": invoice_id})
