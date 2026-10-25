"""LLM provider interface and error types."""

from typing import Protocol

from app.schemas.extraction import ExtractedInvoice


class LLMError(Exception):
    """Permanent failure (bad API key, request rejected). Retrying will not help."""


class LLMRetryableError(LLMError):
    """Temporary failure: timeout, rate limit, server error, or malformed output.
    The same request may well succeed a few seconds later."""


class LLMProvider(Protocol):
    async def extract_invoice(self, ocr_text: str) -> ExtractedInvoice: ...
