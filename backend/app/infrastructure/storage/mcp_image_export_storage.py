"""Read-only bounded adapter for exactly the database-prepared image keys."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Iterable

from app.domain.exceptions.exceptions import StorageError
from app.domain.repositories.interfaces import IObjectStorageRepository
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.imaging.passport_image_cropper import inspect_passport_image
from app.infrastructure.storage.minio_repository import MinioStorageRepository

MAX_IMAGE_SOURCE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_ARCHIVE_BYTES = 256 * 1024 * 1024


class MCPImageExportStorage(IObjectStorageRepository):
    """No object keys are accepted from MCP arguments or returned in tool results."""

    def __init__(
        self,
        storage: MinioStorageRepository,
        allowed_keys: Iterable[str],
        *,
        maximum_source_bytes: int = MAX_IMAGE_SOURCE_BYTES,
    ):
        self.storage = storage
        self.allowed_keys = frozenset(allowed_keys)
        self.maximum_source_bytes = min(MAX_IMAGE_SOURCE_BYTES, maximum_source_bytes)
        self.reserved_bytes = 0
        self._reservation = asyncio.Lock()

    async def get_file(self, key: str) -> bytes:
        if key not in self.allowed_keys:
            raise StorageError("Image is outside the prepared export")
        async with asyncio.timeout(120):
            metadata = await self.storage.stat_file(key)
            size = metadata.size_bytes
            if not 0 < size <= self.maximum_source_bytes:
                raise StorageError("Image exceeds the source size limit")
            async with self._reservation:
                if self.reserved_bytes + size > MAX_IMAGE_ARCHIVE_BYTES:
                    raise StorageError("Images exceed the export size limit")
                # Reservation precedes concurrent reads; failed reads consume their
                # allowance too, keeping fallback reads within the same bound.
                self.reserved_bytes += size
            data, digest = bytearray(), hashlib.sha256()
            async for part in self.storage.stream_file(
                key, start=0, expected_bytes=size, chunk_size=64 * 1024
            ):
                if len(data) + len(part) > size:
                    raise StorageError("Image exceeded its declared size")
                data.extend(part)
                digest.update(part)
            if len(data) != size or (
                metadata.checksum_sha256 is not None
                and not hmac.compare_digest(metadata.checksum_sha256, digest.hexdigest())
            ):
                raise StorageError("Image checksum or length changed")
        content = bytes(data)
        del data
        # Canonical image inspection applies the existing pixel limit and native
        # decode admission before accepting compressed originals into an archive.
        await run_bounded_storage_operations(
            [
                lambda: asyncio.to_thread(inspect_passport_image, content),
            ],
            concurrency=1,
        )
        return content

    async def upload_file(self, file_content: bytes, file_name: str, content_type: str) -> str:
        raise StorageError("Export storage is read-only")

    async def get_presigned_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        raise StorageError("Export storage does not issue direct links")

    async def delete_files(self, keys: list[str]) -> int:
        raise StorageError("Export storage is read-only")
