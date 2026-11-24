"""Private object-storage persistence contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IObjectStorageRepository(ABC):
    """Contract for object storage operations (e.g., S3/MinIO)."""

    @abstractmethod
    async def upload_file(self, file_content: bytes, file_name: str, content_type: str) -> str:
        """Uploads a file and returns its storage key/path."""
        ...

    @abstractmethod
    async def get_file(self, key: str) -> bytes:
        """Downloads a file from object storage."""
        ...

    @abstractmethod
    async def get_presigned_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        """Generates a presigned URL for downloading/viewing a file."""
        ...

    @abstractmethod
    async def delete_files(self, keys: list[str]) -> int:
        """Deletes files from object storage and returns the number requested for deletion."""
        ...
