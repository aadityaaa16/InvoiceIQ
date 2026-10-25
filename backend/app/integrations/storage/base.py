"""Storage interface. Services depend on this, never on a concrete backend."""

from typing import Protocol


class StorageBackend(Protocol):
    """Any object with these methods is a valid backend (structural typing):
    S3Storage in production, an in-memory fake in tests, Azure Blob later."""

    async def upload(self, key: str, data: bytes, content_type: str) -> None: ...

    async def download(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def presigned_url(self, key: str, expires_in: int) -> str:
        """A temporary URL the browser can open directly, without our credentials."""
        ...
