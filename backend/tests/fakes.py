"""In-memory stand-ins for external services. They satisfy the same Protocols as
the real implementations, so the app cannot tell the difference."""

import uuid

from app.schemas.extraction import ExtractedInvoice


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def download(self, key: str) -> bytes:
        return self.objects[key][0]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def presigned_url(self, key: str, expires_in: int) -> str:
        return f"https://storage.example.com/{key}?expires={expires_in}"


class FakeTaskQueue:
    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.fail = False  # set True to simulate the broker being down

    async def enqueue_invoice_processing(self, invoice_id: uuid.UUID) -> None:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.enqueued.append(invoice_id)


class FakeOCR:
    def __init__(self, text: str = "TAX INVOICE\nSharma Distributors\nInvoice No: INV-001") -> None:
        self.text = text
        self.error: Exception | None = None
        self.calls = 0

    def extract_text(self, data: bytes, file_type: str) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        return self.text


class FakeLLM:
    """Returns (or raises) the queued results in order; repeats the last one."""

    def __init__(self, *results: ExtractedInvoice | Exception) -> None:
        self.results = list(results) or [sample_extraction()]
        self.prompts: list[str] = []

    async def extract_invoice(self, ocr_text: str) -> ExtractedInvoice:
        self.prompts.append(ocr_text)
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result


def sample_extraction(**overrides: object) -> ExtractedInvoice:
    data: dict[str, object] = {
        "vendor_name": "Sharma Distributors",
        "vendor_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "INV-001",
        "invoice_date": "2026-09-15",
        "line_items": [
            {
                "description": "Steel rods",
                "hsn_code": "7214",
                "quantity": 10,
                "unit_price": 60,
                "tax_rate": 18,
                "amount": 600,
            },
            {
                "description": "Binding wire",
                "hsn_code": "7217",
                "quantity": 5,
                "unit_price": 80,
                "tax_rate": 18,
                "amount": 400,
            },
        ],
        "subtotal": 1000,
        "cgst": 90,
        "sgst": 90,
        "igst": None,
        "total_amount": 1180,
        "confidence": {
            "vendor_name": 0.98,
            "vendor_gstin": 0.95,
            "invoice_number": 0.97,
            "invoice_date": 0.96,
            "line_items": 0.92,
            "totals": 0.99,
        },
    }
    return ExtractedInvoice.model_validate(data | overrides)
