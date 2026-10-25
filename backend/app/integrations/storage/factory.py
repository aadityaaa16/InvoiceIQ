"""Picks the storage backend from config (STORAGE_BACKEND)."""

from functools import lru_cache

from app.core.config import settings
from app.integrations.storage.base import StorageBackend
from app.integrations.storage.s3 import S3Storage


@lru_cache
def get_storage() -> StorageBackend:
    """One shared backend per process (boto3 clients are expensive to create)."""
    if settings.STORAGE_BACKEND == "s3":
        return S3Storage(
            endpoint_url=settings.S3_ENDPOINT_URL,
            public_endpoint_url=settings.S3_PUBLIC_ENDPOINT_URL,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY.get_secret_value(),
            bucket=settings.S3_BUCKET,
            region=settings.S3_REGION,
        )
    raise NotImplementedError(f"Storage backend '{settings.STORAGE_BACKEND}' is not implemented")
