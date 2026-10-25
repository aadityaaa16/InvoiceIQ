"""Structured JSON logging with a request ID on every line.

One JSON object per line can be searched and filtered by log tools (Azure Log
Analytics, Loki, CloudWatch), e.g. "all logs where request_id = abc123".

Usage:
    logger = logging.getLogger(__name__)
    logger.info("invoice processed", extra={"invoice_id": str(invoice.id), "duration_ms": 812})
"""

import json
import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime

from fastapi import Request, Response

# A ContextVar holds a separate value per request (per asyncio task), so concurrent
# requests never see each other's IDs, unlike a plain global variable.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes every LogRecord has; anything else on a record came from `extra=`.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}

logger = logging.getLogger("app.request")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        # Include fields passed via extra={...}
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)  # containers log to stdout, not files
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Our middleware logs every request with more detail, so silence uvicorn's duplicate.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Assign a request ID, log the request with its duration, echo the ID in a header."""
    # Reuse the caller's ID if it sent one (e.g. from a gateway) so logs can be
    # correlated across services; cap its length so clients can't inject huge values.
    incoming = request.headers.get("X-Request-ID", "")
    request_id = incoming if 0 < len(incoming) <= 64 else uuid.uuid4().hex
    token = request_id_var.set(request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return response
    finally:
        request_id_var.reset(token)
