"""Celery application. Start a worker with:

celery -A app.workers.celery_app worker --loglevel=info --pool=solo   (Windows)
celery -A app.workers.celery_app worker --loglevel=info               (Linux / Docker)
"""

from celery import Celery

from app.core.config import settings

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
