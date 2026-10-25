"""S3-compatible storage (SeaweedFS locally; AWS S3, MinIO, Cloudflare R2 elsewhere)."""

import asyncio
from typing import Any

import boto3
from botocore.config import Config


class S3Storage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        public_endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
    ) -> None:
        self.bucket = bucket
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},  # http://host/bucket/key (needed for local S3)
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
        )
        credentials: dict[str, Any] = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
            "config": config,
        }
        # Used for real operations, from inside our network (e.g. http://seaweedfs:8333).
        self._client = boto3.client("s3", endpoint_url=endpoint_url, **credentials)
        # Presigned URLs are opened by the browser, and the host is part of the signature,
        # so they must be signed for the public address (e.g. http://localhost:8333).
        self._presign_client = boto3.client("s3", endpoint_url=public_endpoint_url, **credentials)

    # boto3 is synchronous; asyncio.to_thread keeps it from blocking the event loop.
    # boto3 clients are thread-safe, so one client can serve all threads.

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def download(self, key: str) -> bytes:
        def _download() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return bytes(response["Body"].read())

        return await asyncio.to_thread(_download)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def presigned_url(self, key: str, expires_in: int) -> str:
        # Signing is a local computation (no network call), so no thread is needed.
        url: str = self._presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
