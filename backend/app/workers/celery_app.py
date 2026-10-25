"""Celery application. Start a worker with:

celery -A app.workers.celery_app worker --loglevel=info --pool=solo   (Windows)
celery -A app.workers.celery_app worker --loglevel=info               (Linux / Docker)
"""

from typing import Any

from celery import Celery, signals

from app.core.config import settings
from app.core.logging import request_id_var, setup_logging

# Task names live here (not in tasks.py) so the API can enqueue by name with
# send_task without importing worker code and its OCR dependencies.
PROCESS_INVOICE_TASK = "invoices.process"

celery_app = Celery(
    "invoiceiq",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",  # never pickle: unpickling untrusted data can run code
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    # Acknowledge a task only after it finishes. If a worker crashes mid-task, the
    # broker re-delivers it instead of losing it (safe because tasks are idempotent).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Take one task at a time: invoices are slow (OCR + LLM), so prefetching several
    # would leave them waiting on a busy worker while other workers sit idle.
    worker_prefetch_multiplier=1,
    result_expires=3600,
)


@signals.setup_logging.connect
def _configure_logging(**_: Any) -> None:
    """Use our JSON logging in the worker too (instead of Celery's default format)."""
    setup_logging(settings.LOG_LEVEL)


@signals.task_prerun.connect
def _set_task_id_as_request_id(task_id: str, **_: Any) -> None:
    """Tag every log line from a task with its task id, like request ids in the API."""
    request_id_var.set(task_id)
