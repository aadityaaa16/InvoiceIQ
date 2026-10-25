"""In-memory stand-ins for external services. They satisfy the same Protocols as
the real implementations, so the app cannot tell the difference."""

import uuid


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
