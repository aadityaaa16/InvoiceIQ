"""Upload helpers: detect the real file type and clean up file names."""

import re
from pathlib import PurePath

# The first bytes ("magic numbers") identify a file's real format. The extension and
# the browser's Content-Type header are chosen by the client and cannot be trusted.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
]

CONTENT_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg"}


def detect_file_type(data: bytes) -> str | None:
    """Return 'pdf', 'png' or 'jpg', or None if the format is not supported."""
    for signature, file_type in _SIGNATURES:
        if data.startswith(signature):
            return file_type
    return None


def sanitize_filename(filename: str) -> str:
    """Keep only the base name (no '../../' paths) and drop control characters."""
    name = PurePath(filename.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:255] or "upload"
