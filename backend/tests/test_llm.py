"""Gemini provider error handling (network mocked) and extraction schema behaviour."""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors

from app.integrations.llm.base import LLMError, LLMRetryableError
from app.integrations.llm.gemini import GeminiProvider
from app.integrations.llm.prompts import MAX_OCR_CHARS, build_user_prompt
from app.schemas.extraction import ExtractedInvoice
from tests.fakes import sample_extraction


def provider_returning(result: Any) -> GeminiProvider:
    """A GeminiProvider whose network call returns `result` (or raises it)."""
    provider = GeminiProvider(api_key="test-key", model="gemini-test", timeout_seconds=5)

    async def generate_content(**_: Any) -> Any:
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result)

    provider.client = SimpleNamespace(  # type: ignore[assignment]
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    )
    return provider


async def test_valid_response_is_parsed() -> None:
    payload = sample_extraction().model_dump_json()
    result = await provider_returning(payload).extract_invoice("ocr text")
    assert result.invoice_number == "INV-001"


@pytest.mark.parametrize("code", [429, 500, 503])
async def test_rate_limit_and_server_errors_are_retryable(code: int) -> None:
    error = errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})
    with pytest.raises(LLMRetryableError):
        await provider_returning(error).extract_invoice("ocr text")


@pytest.mark.parametrize("code", [400, 401, 403])
async def test_client_errors_are_permanent(code: int) -> None:
    error = errors.APIError(code, {"error": {"code": code, "message": "bad", "status": "X"}})
    with pytest.raises(LLMError) as exc_info:
        await provider_returning(error).extract_invoice("ocr text")
    assert not isinstance(exc_info.value, LLMRetryableError)


async def test_timeout_is_retryable() -> None:
    with pytest.raises(LLMRetryableError):
        await provider_returning(httpx.ReadTimeout("slow")).extract_invoice("ocr text")


@pytest.mark.parametrize(
    "bad_output",
    ["not json at all", '{"vendor_name": "x"}', json.dumps({"line_items": "oops"})],
)
async def test_invalid_json_is_retryable(bad_output: str) -> None:
    with pytest.raises(LLMRetryableError, match="invalid JSON"):
        await provider_returning(bad_output).extract_invoice("ocr text")


def test_amounts_parse_to_exact_decimals() -> None:
    raw = sample_extraction().model_dump(mode="json") | {"cgst": 0.1, "sgst": 0.2}
    parsed = ExtractedInvoice.model_validate_json(json.dumps(raw))
    assert parsed.cgst is not None and parsed.sgst is not None
    assert parsed.cgst + parsed.sgst == Decimal("0.3")  # would fail with floats


def test_schema_sent_to_llm_uses_plain_numbers_for_amounts() -> None:
    schema = ExtractedInvoice.model_json_schema()
    total = schema["properties"]["total_amount"]["anyOf"]
    assert {"type": "number"} in total


def test_confidence_out_of_range_is_rejected() -> None:
    raw = sample_extraction().model_dump(mode="json")
    raw["confidence"]["totals"] = 1.5
    with pytest.raises(ValueError):
        ExtractedInvoice.model_validate(raw)


def test_prompt_truncates_and_delimits_ocr_text() -> None:
    prompt = build_user_prompt("A" * (MAX_OCR_CHARS + 500))
    assert prompt.count("A") == MAX_OCR_CHARS
    assert "<document>" in prompt and "</document>" in prompt
