"""
MinIO / S3 Storage Repository
=============================
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import StorageError
from app.domain.repositories.interfaces import IObjectStorageRepository

logger = get_logger(__name__)

_SHA256_METADATA_KEY = "sha256"
_SHA256_HEX_LENGTH = 64


@dataclass(frozen=True, slots=True)
class ObjectIntegrityMetadata:
    """Bounded object metadata used by mobile integrity authorization."""

    size_bytes: int
    checksum_sha256: str | None
    content_type: str | None


@lru_cache(maxsize=1)
def _shared_s3_clients() -> tuple[Any, Any]:
    """Build one thread-safe boto client pair per backend worker process."""

    settings = get_settings().s3
    client_config = Config(
        signature_version="s3v4",
        connect_timeout=settings.connect_timeout_seconds,
        read_timeout=settings.read_timeout_seconds,
        max_pool_connections=settings.max_pool_connections,
        retries={
            "total_max_attempts": settings.max_attempts,
            "mode": "standard",
        },
    )
    client = boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
        config=client_config,
    )
    presign_client = boto3.client(
        "s3",
        endpoint_url=settings.public_endpoint_url or settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
        config=client_config,
    )
    return client, presign_client


class MinioStorageRepository(IObjectStorageRepository):
    """Implementation of object storage using boto3."""

    def __init__(self) -> None:
        self.settings = get_settings().s3
        self._client, self._presign_client = _shared_s3_clients()

    async def ensure_bucket_exists(self) -> None:
        """Provision the bucket during startup, never in a request constructor."""

        try:
            await asyncio.to_thread(
                self._client.head_bucket,
                Bucket=self.settings.bucket_name,
            )
        except ClientError as e:
            error_code = str(e.response.get("Error", {}).get("Code", ""))
            if error_code in {"404", "NoSuchBucket", "NotFound"}:
                logger.info("s3_bucket_creating")
                await asyncio.to_thread(
                    self._client.create_bucket,
                    Bucket=self.settings.bucket_name,
                )
            else:
                logger.error(
                    "s3_bucket_check_failed",
                    error_type=type(e).__name__,
                )
                raise StorageError("Passport image storage is not available.") from e
        except Exception as e:
            logger.error(
                "s3_bucket_check_failed",
                error_type=type(e).__name__,
            )
            raise StorageError("Passport image storage is not available.") from e

    async def upload_file(self, file_content: bytes, file_name: str, content_type: str) -> str:
        """Uploads file synchronously in a thread pool to avoid blocking the event loop."""
        try:
            checksum_sha256 = hashlib.sha256(file_content).hexdigest()
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self.settings.bucket_name,
                Key=file_name,
                Body=file_content,
                ContentType=content_type,
                Metadata={_SHA256_METADATA_KEY: checksum_sha256},
            )
            return file_name
        except Exception as e:
            logger.error(
                "s3_upload_failed",
                object_key_hash=self._key_hash(file_name),
                error_type=type(e).__name__,
            )
            raise StorageError(
                "Passport image storage is temporarily unavailable. Please try again."
            ) from e

    async def get_file(self, key: str) -> bytes:
        """Downloads a stored object without blocking the event loop."""
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self.settings.bucket_name,
                Key=key,
            )
            body = response["Body"]
            try:
                return await asyncio.to_thread(body.read)
            finally:
                await asyncio.to_thread(body.close)
        except Exception as e:
            logger.error(
                "s3_download_failed",
                object_key_hash=self._key_hash(key),
                error_type=type(e).__name__,
            )
            raise StorageError(
                "The stored passport image is temporarily unavailable. Please try again."
            ) from e

    async def stat_file(self, key: str) -> ObjectIntegrityMetadata:
        """Read size and optional trusted upload checksum without downloading the body."""

        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self.settings.bucket_name,
                Key=key,
            )
            raw_size = response.get("ContentLength")
            if isinstance(raw_size, bool) or not isinstance(raw_size, int) or raw_size < 0:
                raise StorageError("The stored document did not provide a safe content length.")

            raw_metadata = response.get("Metadata")
            raw_checksum = (
                raw_metadata.get(_SHA256_METADATA_KEY)
                if isinstance(raw_metadata, dict)
                else None
            )
            checksum: str | None = None
            if raw_checksum is not None:
                if not isinstance(raw_checksum, str):
                    raise StorageError("The stored document integrity metadata is invalid.")
                checksum = raw_checksum.strip().casefold()
                if (
                    len(checksum) != _SHA256_HEX_LENGTH
                    or any(character not in "0123456789abcdef" for character in checksum)
                ):
                    raise StorageError("The stored document integrity metadata is invalid.")

            raw_content_type = response.get("ContentType")
            content_type = (
                raw_content_type.strip().casefold()
                if isinstance(raw_content_type, str) and raw_content_type.strip()
                else None
            )
            return ObjectIntegrityMetadata(
                size_bytes=raw_size,
                checksum_sha256=checksum,
                content_type=content_type,
            )
        except StorageError:
            raise
        except Exception as e:
            logger.error(
                "s3_stat_failed",
                object_key_hash=self._key_hash(key),
                error_type=type(e).__name__,
            )
            raise StorageError(
                "The stored document is temporarily unavailable. Please try again."
            ) from e

    async def calculate_file_sha256(
        self,
        key: str,
        *,
        expected_bytes: int,
        chunk_size: int = 64 * 1024,
    ) -> str:
        """Hash one exact object body with bounded memory for legacy metadata repair."""

        if expected_bytes < 1 or chunk_size < 1024:
            raise ValueError("Invalid object hash bounds")
        digest = hashlib.sha256()
        consumed = 0
        async for chunk in self.stream_file(
            key,
            start=0,
            expected_bytes=expected_bytes,
            chunk_size=chunk_size,
        ):
            consumed += len(chunk)
            digest.update(chunk)
        if consumed != expected_bytes:
            # stream_file already fails on short/long streams. Keep this guard so
            # future implementations cannot accidentally cache a partial digest.
            raise StorageError("The stored document stream ended unexpectedly.")
        return digest.hexdigest()

    async def get_file_range(self, key: str, *, start: int, end: int) -> bytes:
        """Read one bounded inclusive range without materializing the full object."""

        if start < 0 or end < start:
            raise ValueError("Invalid object byte range")
        expected = end - start + 1
        body: Any | None = None
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self.settings.bucket_name,
                Key=key,
                Range=f"bytes={start}-{end}",
            )
            body = response["Body"]
            payload = await asyncio.to_thread(body.read, expected + 1)
            if len(payload) != expected:
                raise StorageError("The stored document range was incomplete.")
            return bytes(payload)
        except StorageError:
            raise
        except Exception as e:
            logger.error(
                "s3_range_download_failed",
                object_key_hash=self._key_hash(key),
                error_type=type(e).__name__,
            )
            raise StorageError(
                "The stored document is temporarily unavailable. Please try again."
            ) from e
        finally:
            if body is not None:
                await asyncio.to_thread(body.close)

    async def stream_file(
        self,
        key: str,
        *,
        start: int,
        expected_bytes: int,
        chunk_size: int = 64 * 1024,
    ) -> AsyncIterator[bytes]:
        """Stream an exact bounded range while keeping worker memory constant."""

        if start < 0 or expected_bytes < 1 or chunk_size < 1024:
            raise ValueError("Invalid object stream bounds")
        body: Any | None = None
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self.settings.bucket_name,
                Key=key,
                Range=f"bytes={start}-",
            )
            body = response["Body"]
            content_length = response.get("ContentLength")
            if content_length is not None and int(content_length) != expected_bytes:
                raise StorageError("The stored document size changed during download.")
            remaining = expected_bytes
            while remaining:
                chunk = await asyncio.to_thread(body.read, min(chunk_size, remaining))
                if not chunk:
                    raise StorageError("The stored document stream ended unexpectedly.")
                if len(chunk) > remaining:
                    raise StorageError("The stored document exceeded its authorized size.")
                remaining -= len(chunk)
                yield bytes(chunk)
            if content_length is None:
                extra = await asyncio.to_thread(body.read, 1)
                if extra:
                    raise StorageError("The stored document exceeded its authorized size.")
        except StorageError:
            raise
        except Exception as e:
            logger.error(
                "s3_stream_download_failed",
                object_key_hash=self._key_hash(key),
                error_type=type(e).__name__,
            )
            raise StorageError(
                "The stored document is temporarily unavailable. Please try again."
            ) from e
        finally:
            if body is not None:
                await asyncio.to_thread(body.close)

    async def copy_file(self, source_key: str, destination_key: str) -> str:
        """Copy a private object inside the configured bucket without downloading it."""

        try:
            await asyncio.to_thread(
                self._client.copy_object,
                Bucket=self.settings.bucket_name,
                Key=destination_key,
                CopySource={"Bucket": self.settings.bucket_name, "Key": source_key},
            )
            return destination_key
        except Exception as e:
            logger.error(
                "s3_copy_failed",
                source_key_hash=self._key_hash(source_key),
                destination_key_hash=self._key_hash(destination_key),
                error_type=type(e).__name__,
            )
            raise StorageError(
                "Document storage is temporarily unavailable. Please try again."
            ) from e

    async def get_presigned_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        """Generates a presigned URL synchronously in a thread pool."""
        try:
            url = await asyncio.to_thread(
                self._presign_client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self.settings.bucket_name, "Key": key},
                ExpiresIn=expires_in_seconds,
            )
            return str(url)
        except Exception as e:
            logger.error(
                "s3_presign_failed",
                object_key_hash=self._key_hash(key),
                error_type=type(e).__name__,
            )
            raise StorageError(
                "The passport image preview is temporarily unavailable. Please try again."
            ) from e

    async def delete_files(self, keys: list[str]) -> int:
        """Deletes stored objects without blocking the event loop."""
        unique_keys = [key for key in dict.fromkeys(keys) if key]
        if not unique_keys:
            return 0

        deleted_count = 0
        failed_count = 0
        try:
            for index in range(0, len(unique_keys), 1000):
                chunk = unique_keys[index : index + 1000]
                response = await asyncio.to_thread(
                    self._client.delete_objects,
                    Bucket=self.settings.bucket_name,
                    Delete={
                        "Objects": [{"Key": key} for key in chunk],
                        "Quiet": True,
                    },
                )
                errors = response.get("Errors") or []
                failed_count += len(errors)
                deleted_count += len(chunk) - len(errors)
            if failed_count:
                logger.error(
                    "s3_delete_partially_failed",
                    deleted_count=deleted_count,
                    failed_count=failed_count,
                )
                raise StorageError(
                    "Some stored passport files could not be removed. Please try again."
                )
            return deleted_count
        except StorageError:
            raise
        except Exception as e:
            logger.error(
                "s3_delete_failed",
                error_type=type(e).__name__,
                object_count=len(unique_keys),
            )
            raise StorageError(
                "Stored passport files could not be removed. Please try again."
            ) from e

    async def list_files(
        self,
        *,
        prefix: str,
        limit: int = 5_000,
        start_after: str | None = None,
    ) -> list[tuple[str, datetime | None]]:
        """List a bounded internal namespace for storage reconciliation."""

        normalized_prefix = prefix.strip()
        if not normalized_prefix or limit < 1:
            raise ValueError("A non-empty prefix and positive limit are required")

        def _list() -> list[tuple[str, datetime | None]]:
            objects: list[tuple[str, datetime | None]] = []
            continuation_token: str | None = None
            while len(objects) < limit:
                request: dict[str, Any] = {
                    "Bucket": self.settings.bucket_name,
                    "Prefix": normalized_prefix,
                    "MaxKeys": min(1_000, limit - len(objects)),
                }
                if continuation_token:
                    request["ContinuationToken"] = continuation_token
                elif start_after:
                    request["StartAfter"] = start_after
                response = self._client.list_objects_v2(**request)
                for item in response.get("Contents") or []:
                    key = item.get("Key")
                    if isinstance(key, str) and key.startswith(normalized_prefix):
                        modified = item.get("LastModified")
                        objects.append((key, modified if isinstance(modified, datetime) else None))
                if not response.get("IsTruncated") or len(objects) >= limit:
                    break
                token = response.get("NextContinuationToken")
                if not isinstance(token, str) or not token:
                    break
                continuation_token = token
            return objects

        try:
            return await asyncio.to_thread(_list)
        except Exception as e:
            logger.error(
                "s3_list_failed",
                error_type=type(e).__name__,
                prefix_hash=self._key_hash(normalized_prefix),
            )
            raise StorageError(
                "Stored passport files could not be reconciled. Please try again."
            ) from e

    @staticmethod
    def _key_hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
