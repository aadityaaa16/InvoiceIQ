"""Integration test against the real S3-compatible storage from docker compose.

Skipped automatically when the storage service is not running.
"""

import socket
import urllib.request
import uuid
from urllib.parse import urlparse

import pytest

from app.core.config import settings
from app.integrations.storage.factory import get_storage


def _storage_reachable() -> bool:
    url = urlparse(settings.S3_ENDPOINT_URL)
    try:
        with socket.create_connection((url.hostname or "localhost", url.port or 80), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _storage_reachable(), reason="S3 storage not running")


async def test_s3_upload_download_presign_delete() -> None:
    storage = get_storage()
    key = f"tests/{uuid.uuid4()}.txt"

    await storage.upload(key, b"hello", "text/plain")
    assert await storage.download(key) == b"hello"

    # A browser (no credentials) can fetch the object through the presigned URL.
    url = await storage.presigned_url(key, expires_in=60)
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.read() == b"hello"

    await storage.delete(key)
