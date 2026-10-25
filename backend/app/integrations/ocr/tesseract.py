"""Tesseract OCR. PDFs are rendered to images with pdf2image (Poppler) first."""

import io

import pytesseract
from pdf2image import convert_from_bytes
from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError
from PIL import Image, ImageOps

from app.integrations.ocr.base import OCRError

MIN_TEXT_LENGTH = 20  # less than this means a blank or unreadable scan


class TesseractOCR:
    def __init__(
        self,
        *,
        tesseract_cmd: str | None = None,
        poppler_path: str | None = None,
        dpi: int = 300,  # 300 DPI is the usual sweet spot for OCR accuracy vs speed
        max_pages: int = 10,  # invoices are short; caps work on huge or malicious PDFs
        language: str = "eng",
    ) -> None:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.poppler_path = poppler_path
        self.dpi = dpi
        self.max_pages = max_pages
        self.language = language

    def extract_text(self, data: bytes, file_type: str) -> str:
        images = self._to_images(data, file_type)
        pages = [
            pytesseract.image_to_string(self._preprocess(image), lang=self.language)
            for image in images
        ]
        text = "\n\n".join(
            f"--- page {number} ---\n{page.strip()}" for number, page in enumerate(pages, 1)
        )
        if sum(len(page.strip()) for page in pages) < MIN_TEXT_LENGTH:
            raise OCRError("No readable text found in the document")
        return text

    def _to_images(self, data: bytes, file_type: str) -> list[Image.Image]:
        try:
            if file_type == "pdf":
                return list(
                    convert_from_bytes(
                        data,
                        dpi=self.dpi,
                        first_page=1,
                        last_page=self.max_pages,
                        # None means "find Poppler on PATH" (pdf2image's own default,
                        # though its type hint omits None). Set POPPLER_PATH on Windows.
                        poppler_path=self.poppler_path,  # type: ignore[arg-type]
                    )
                )
            image = Image.open(io.BytesIO(data))
            # Image.open is lazy: it reads only the header. load() decodes the pixels now,
            # so a truncated or corrupt file fails here, inside this try block.
            image.load()
            return [image]
        # OSError covers truncated images (UnidentifiedImageError is a subclass of it).
        except (PDFPageCountError, PDFSyntaxError, OSError) as exc:
            raise OCRError(f"Could not read the {file_type} file: {exc}") from exc

    @staticmethod
    def _preprocess(image: Image.Image) -> Image.Image:
        # Phone photos store rotation in EXIF metadata; without this, a portrait
        # photo is OCR'd sideways and produces garbage.
        image = ImageOps.exif_transpose(image) or image
        # Grayscale removes colour noise (stamps, coloured letterheads).
        return image.convert("L")
