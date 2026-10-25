"""OCR interface. Tesseract today; Azure Document Intelligence could implement it later."""

from typing import Protocol


class OCRError(Exception):
    """The document cannot be read (corrupt file, blank scan). Retrying will not help."""


class OCRProvider(Protocol):
    def extract_text(self, data: bytes, file_type: str) -> str:
        """Return the document's text. Synchronous: OCR is CPU-bound work."""
        ...
