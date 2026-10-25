"""Real Tesseract test. Skipped where Tesseract isn't installed (e.g. Windows host);
runs inside the Docker image and in CI."""

import io
import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.integrations.ocr.base import OCRError
from app.integrations.ocr.tesseract import TesseractOCR

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")


def _png(text: str) -> bytes:
    image = Image.new("RGB", (1400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((40, 40), text, fill="black", font=ImageFont.load_default(size=48))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_reads_text_from_image() -> None:
    text = TesseractOCR().extract_text(_png("TAX INVOICE\nInvoice No: INV-2026-001"), "png")
    assert "INVOICE" in text.upper()
    assert "2026" in text


def test_blank_image_raises_ocr_error() -> None:
    with pytest.raises(OCRError, match="No readable text"):
        TesseractOCR().extract_text(_png(""), "png")


def test_corrupt_file_raises_ocr_error() -> None:
    with pytest.raises(OCRError):
        TesseractOCR().extract_text(b"\x89PNG\r\n\x1a\n corrupted", "png")
