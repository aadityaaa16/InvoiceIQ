"""Google Gemini provider using structured output (JSON matching our schema)."""

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.integrations.llm.base import LLMError, LLMRetryableError
from app.integrations.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas.extraction import ExtractedInvoice

# HTTP status codes worth retrying: rate limited, or a temporary server-side problem.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class GeminiProvider:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: int) -> None:
        self.model = model
        self.client = genai.Client(
            api_key=api_key,
            # Retries are handled by our Celery task (with backoff and status tracking),
            # so the SDK should fail fast instead of retrying silently on its own.
            http_options=types.HttpOptions(timeout=timeout_seconds * 1000),
        )
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,  # extraction, not creativity: same input -> same output
            response_mime_type="application/json",
            # Structured output: the model is constrained to this JSON Schema.
            response_json_schema=ExtractedInvoice.model_json_schema(),
        )

    async def extract_invoice(self, ocr_text: str) -> ExtractedInvoice:
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=build_user_prompt(ocr_text), config=self.config
            )
        except errors.APIError as exc:
            if exc.code in _RETRYABLE_STATUS:
                raise LLMRetryableError(f"Gemini API error {exc.code}") from exc
            raise LLMError(f"Gemini API error {exc.code}: {exc.message}") from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LLMRetryableError(f"Gemini request failed: {type(exc).__name__}") from exc

        # Even with structured output, validate: never trust the model's JSON blindly.
        # A malformed answer is often fixed by simply asking again, so it is retryable.
        try:
            return ExtractedInvoice.model_validate_json(response.text or "")
        except ValidationError as exc:
            raise LLMRetryableError(
                f"LLM returned invalid JSON ({exc.error_count()} errors)"
            ) from exc
