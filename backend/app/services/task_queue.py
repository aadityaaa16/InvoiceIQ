"""Background job dispatch, behind an interface so tests need no broker or worker."""

import asyncio
import uuid
from typing import Protocol

from app.workers.celery_app import PROCESS_INVOICE_TASK, celery_app


class TaskQueue(Protocol):
    async def enqueue_invoice_processing(self, invoice_id: uuid.UUID) -> None: ...


class CeleryTaskQueue:
    async def enqueue_invoice_processing(self, invoice_id: uuid.UUID) -> None:
        # send_task enqueues by name: the API does not import the task module.
        # It is a quick synchronous Redis call, so run it off the event loop.
        await asyncio.to_thread(celery_app.send_task, PROCESS_INVOICE_TASK, args=[str(invoice_id)])


def get_task_queue() -> TaskQueue:
    return CeleryTaskQueue()
