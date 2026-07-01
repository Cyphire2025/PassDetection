"""
MinIO / S3 Storage Repository
=============================
"""

import asyncio
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
        self._client = boto3.client(
            "s3",
            endpoint_url=self.settings.endpoint_url,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.secret_access_key,
            region_name=self.settings.region,
            config=Config(signature_version="s3v4"),
        )
        self._presign_client = boto3.client(
            "s3",
            endpoint_url=self.settings.public_endpoint_url or self.settings.endpoint_url,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.secret_access_key,
            region_name=self.settings.region,
            config=Config(signature_version="s3v4"),
        )
        # Ensure bucket exists
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """Create bucket if it doesn't exist."""
        try:
            self._client.head_bucket(Bucket=self.settings.bucket_name)
        except ClientError as e:
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                logger.info(f"Creating bucket {self.settings.bucket_name}")
                self._client.create_bucket(Bucket=self.settings.bucket_name)
            else:
                logger.error(f"Failed to check/create bucket: {e}")

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
            logger.error("s3_upload_failed", key=file_name, error=str(e))
            raise StorageError(f"Failed to upload file to storage: {str(e)}")

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
            logger.error("s3_download_failed", key=key, error=str(e))
            raise StorageError(f"Failed to download file from storage: {str(e)}")

    async def get_presigned_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        """Generates a presigned URL synchronously in a thread pool."""
        try:
            url = await asyncio.to_thread(
                self._presign_client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self.settings.bucket_name, "Key": key},
                ExpiresIn=expires_in_seconds,
            )
            return url
        except Exception as e:
            logger.error("s3_presign_failed", key=key, error=str(e))
            raise StorageError(f"Failed to generate presigned URL: {str(e)}")
