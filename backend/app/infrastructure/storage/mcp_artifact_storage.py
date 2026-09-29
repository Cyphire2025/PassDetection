"""Conditional private transfer writes using the existing bounded S3 client pool."""

from __future__ import annotations

import asyncio
from typing import BinaryIO

from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.storage.minio_repository import MinioStorageRepository


class MCPArtifactStorage(MinioStorageRepository):
    async def put_transfer(
        self, source: BinaryIO, *, key: str, size: int, sha256: str, media_type: str
    ) -> None:
        # Only service-generated private keys can enter this adapter. A random
        # key plus a conditional write preserves any existing object even on a
        # UUID collision. Unsupported conditional writes fail closed.
        if not key.startswith("mcp-transfers/v1/") or size < 1:
            raise ValueError("Invalid private transfer")

        def put() -> None:
            source.seek(0)
            self._client.put_object(
                Bucket=self.settings.bucket_name,
                Key=key,
                Body=source,
                ContentLength=size,
                ContentType=media_type,
                Metadata={"sha256": sha256},
                IfNoneMatch="*",
            )

        try:
            # Do not abandon the worker on cancellation: the caller owns and
            # closes this temporary file after the in-flight S3 read finishes.
            await run_bounded_storage_operations([lambda: asyncio.to_thread(put)], concurrency=1)
        except Exception as exc:
            raise StorageError("Temporary transfer storage is unavailable") from exc
