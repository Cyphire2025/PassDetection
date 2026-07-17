"""
MinIO / S3 Storage Repository
=============================
"""

import asyncio
import hashlib

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import StorageError
from app.domain.repositories.interfaces import IObjectStorageRepository

logger = get_logger(__name__)


class MinioStorageRepository(IObjectStorageRepository):
    """Implementation of object storage using boto3."""

    def __init__(self) -> None:
        self.settings = get_settings().s3
        client_config = Config(
            signature_version="s3v4",
            connect_timeout=self.settings.connect_timeout_seconds,
            read_timeout=self.settings.read_timeout_seconds,
            retries={
                "total_max_attempts": self.settings.max_attempts,
                "mode": "standard",
            },
        )
        self._client = boto3.client(
            "s3",
            endpoint_url=self.settings.endpoint_url,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.secret_access_key,
            region_name=self.settings.region,
            config=client_config,
        )
        self._presign_client = boto3.client(
            "s3",
            endpoint_url=self.settings.public_endpoint_url or self.settings.endpoint_url,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.secret_access_key,
            region_name=self.settings.region,
            config=client_config,
        )
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
                raise StorageError(
                    "Passport image storage is not available."
                ) from e
        except Exception as e:
            logger.error(
                "s3_bucket_check_failed",
                error_type=type(e).__name__,
            )
            raise StorageError(
                "Passport image storage is not available."
            ) from e

    async def upload_file(self, file_content: bytes, file_name: str, content_type: str) -> str:
        """Uploads file synchronously in a thread pool to avoid blocking the event loop."""
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self.settings.bucket_name,
                Key=file_name,
                Body=file_content,
                ContentType=content_type,
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
            return await asyncio.to_thread(body.read)
        except Exception as e:
            logger.error(
                "s3_download_failed",
                object_key_hash=self._key_hash(key),
                error_type=type(e).__name__,
            )
            raise StorageError(
                "The stored passport image is temporarily unavailable. Please try again."
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
                chunk = unique_keys[index:index + 1000]
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

    @staticmethod
    def _key_hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
