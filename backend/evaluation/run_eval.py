"""Run the real OCR + LLM pipeline on labelled invoices and report field-level accuracy.

Expects pairs of files: invoice_001.png + invoice_001.json (ground truth).
Needs Tesseract and LLM_API_KEY, so run it inside the worker container:

    docker compose run --rm -v ./backend/evaluation:/app/evaluation worker \\
        python -m evaluation.run_eval --data evaluation/data/synthetic
"""

import argparse
import asyncio
import json
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.integrations.factories import get_llm_provider
from app.integrations.llm.base import LLMRetryableError
from app.integrations.ocr.tesseract import TesseractOCR
from app.schemas.extraction import ExtractedInvoice
from app.services.validation import InvoiceFields, validate_invoice

FIELDS = [
    "vendor_gstin",
    "invoice_number",
    "invoice_date",
    "subtotal",
    "cgst",
    "sgst",
    "igst",
    "total_amount",
    "line_item_count",
]


def _norm(field: str, value: Any) -> Any:
    """Compare meaning, not formatting."""
    if value in (None, ""):
        return None
    if field in ("subtotal", "cgst", "sgst", "igst", "total_amount"):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    if field == "invoice_number":
        return re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if field == "invoice_date":
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    return str(value).upper().strip()


def compare(truth: dict[str, Any], got: ExtractedInvoice) -> dict[str, bool]:
    predicted = got.model_dump() | {"line_item_count": len(got.line_items)}
    truth = truth | {"line_item_count": len(truth["line_items"])}
    return {f: _norm(f, truth.get(f)) == _norm(f, predicted.get(f)) for f in FIELDS}


async def extract_with_retry(llm: Any, text: str) -> ExtractedInvoice:
    for attempt in range(4):
        try:
            return await llm.extract_invoice(text)  # type: ignore[no-any-return]
        except LLMRetryableError:
            if attempt == 3:
                raise
            await asyncio.sleep(10 * (attempt + 1))  # free-tier rate limits
    raise AssertionError("unreachable")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="evaluation/data/synthetic")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between LLM calls")
    args = parser.parse_args()

    ocr, llm = TesseractOCR(), get_llm_provider()
    rows: list[dict[str, Any]] = []
    for image in sorted(Path(args.data).glob("*.png")):
        truth = json.loads(image.with_suffix(".json").read_text())
        start = time.perf_counter()
        text = await asyncio.to_thread(ocr.extract_text, image.read_bytes(), "png")
        ocr_s = time.perf_counter() - start
        extracted = await extract_with_retry(llm, text)
        total_s = time.perf_counter() - start
        issues = validate_invoice(
            InvoiceFields(
                vendor_gstin=extracted.vendor_gstin,
                invoice_number=extracted.invoice_number,
                invoice_date=extracted.invoice_date,
                line_item_amounts=[i.amount for i in extracted.line_items],
                subtotal=extracted.subtotal,
                cgst=extracted.cgst,
                sgst=extracted.sgst,
                igst=extracted.igst,
                total_amount=extracted.total_amount,
            ),
            today=datetime.now(UTC).date(),
            tolerance=settings.AMOUNT_TOLERANCE,
        )
        correct = compare(truth, extracted)
        auto = (
            not issues
            and extracted.overall_confidence() >= settings.AUTO_APPROVE_CONFIDENCE_THRESHOLD
        )
        rows.append(
            {
                "file": image.name,
                "kind": "photo" if "photo" in image.name else "scan",
                "correct": correct,
                "all_correct": all(correct.values()),
                "auto_approved": auto,
                "issues": [i.code for i in issues],
                "ocr_seconds": round(ocr_s, 2),
                "total_seconds": round(total_s, 2),
            }
        )
        print(
            f"{image.name}: {sum(correct.values())}/{len(FIELDS)} fields correct, "
            f"{'AUTO-APPROVED' if auto else 'review'}, {total_s:.1f}s"
        )
        await asyncio.sleep(args.delay)

    n = len(rows)
    report = {
        "model": settings.LLM_MODEL,
        "invoices": n,
        "field_accuracy": {f: round(sum(r["correct"][f] for r in rows) / n, 3) for f in FIELDS},
        "fully_correct_rate": round(sum(r["all_correct"] for r in rows) / n, 3),
        "by_kind": {
            kind: round(sum(r["all_correct"] for r in group) / len(group), 3)
            for kind in ("scan", "photo")
            if (group := [r for r in rows if r["kind"] == kind])
        },
        "auto_approval_rate": round(sum(r["auto_approved"] for r in rows) / n, 3),
        # Safety metric: an auto-approved invoice with any wrong field is the costly failure.
        "wrong_but_auto_approved": sum(r["auto_approved"] and not r["all_correct"] for r in rows),
        "avg_seconds": round(sum(r["total_seconds"] for r in rows) / n, 2),
        "avg_ocr_seconds": round(sum(r["ocr_seconds"] for r in rows) / n, 2),
        "rows": rows,
    }
    out = Path(args.data).parent / "results.json"
    out.write_text(json.dumps(report, indent=2))
    print("\n| Field | Accuracy |\n|---|---|")
    for field, accuracy in report["field_accuracy"].items():
        print(f"| {field} | {accuracy:.0%} |")
    summary = {k: v for k, v in report.items() if k not in ("rows", "field_accuracy")}
    print(f"\n{json.dumps(summary, indent=2)}\nSaved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
