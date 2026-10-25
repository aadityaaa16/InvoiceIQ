"""Build OCR and LLM providers from config (OCR_PROVIDER, LLM_PROVIDER)."""

from functools import lru_cache

from app.core.config import settings
from app.integrations.llm.base import LLMError, LLMProvider
from app.integrations.ocr.base import OCRProvider


@lru_cache
def get_ocr_provider() -> OCRProvider:
    # Imported here so the API process, which never runs OCR, doesn't load it.
    from app.integrations.ocr.tesseract import TesseractOCR

    return TesseractOCR(tesseract_cmd=settings.TESSERACT_CMD, poppler_path=settings.POPPLER_PATH)


def get_llm_provider() -> LLMProvider:
    """Not cached: the async HTTP client inside is bound to the event loop it first
    runs on, and each Celery task runs in its own fresh event loop."""
    if settings.LLM_API_KEY is None:
        raise LLMError("LLM_API_KEY is not configured")
    if settings.LLM_PROVIDER == "gemini":
        from app.integrations.llm.gemini import GeminiProvider

        return GeminiProvider(
            api_key=settings.LLM_API_KEY.get_secret_value(),
            model=settings.LLM_MODEL,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        )
    raise NotImplementedError(f"LLM provider '{settings.LLM_PROVIDER}' is not implemented")
