import pytest

from app.utils.files import detect_file_type, sanitize_filename


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"%PDF-1.4 ...", "pdf"),
        (b"\x89PNG\r\n\x1a\n...", "png"),
        (b"\xff\xd8\xff\xe0...", "jpg"),
        (b"GIF89a...", None),
        (b"<html>", None),
        (b"", None),
    ],
)
def test_detect_file_type(data: bytes, expected: str | None) -> None:
    assert detect_file_type(data) == expected


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("invoice.pdf", "invoice.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\bill.png", "bill.png"),
        ("bad\x00name\n.pdf", "badname.pdf"),
        ("", "upload"),
    ],
)
def test_sanitize_filename(raw: str, clean: str) -> None:
    assert sanitize_filename(raw) == clean
