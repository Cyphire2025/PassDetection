"""Durable malware decisions and encrypted private quarantine handling."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.settings import Settings, get_settings
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.models import UntrustedUploadScanModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.security.upload_validator import (
    MalwareScanner,
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
    UploadValidator,
    ValidatedUpload,
    malware_scanner_from_settings,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository


class UploadSecurityEvidenceError(ImageValidationError):
    """Raised when the durable security decision cannot be recorded safely."""


class QuarantineLocatorError(ValueError):
    """Raised when a retained private quarantine locator cannot be authenticated."""


@dataclass(frozen=True, slots=True)
class UploadSecurityContext:
    ingestion_flow: str
    agency_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


class DigestBoundScanner:
    """Allow parsing only the exact byte string that already passed scanning."""

    def __init__(self, expected_sha256: str) -> None:
        self._expected_sha256 = expected_sha256

    def scan(self, content: bytes) -> None:
        observed = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(observed, self._expected_sha256):
            raise MalwareScanRejectedError("Uploaded bytes changed after security scanning")


class UploadSecurityService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        scanner: MalwareScanner | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        storage: MinioStorageRepository | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._scanner = scanner or malware_scanner_from_settings(self._settings)
        self._session_factory = session_factory or AsyncSessionFactory
        self._storage = storage or MinioStorageRepository()

    async def validate_image(
        self,
        *,
        content: bytes,
        filename: str | None,
        declared_content_type: str | None,
        context: UploadSecurityContext,
        max_bytes: int | None = None,
    ) -> ValidatedUpload:
        if not content:
            await self._record(
                content=content,
                declared_media_type=declared_content_type,
                context=context,
                scan_status="malformed",
                disposition="rejected",
                error_code="EMPTY_UPLOAD",
            )
            raise ImageValidationError("Uploaded file is empty")
        active_limit = min(
            self._settings.upload_max_file_size_bytes,
            max_bytes if max_bytes is not None else self._settings.upload_max_file_size_bytes,
        )
        if len(content) > active_limit:
            await self._record(
                content=content,
                declared_media_type=declared_content_type,
                context=context,
                scan_status="oversized",
                disposition="rejected",
                error_code="UPLOAD_TOO_LARGE",
            )
            raise ImageValidationError("Uploaded file exceeds the configured size limit")

        digest = await self._scan_original(
            content=content,
            declared_media_type=declared_content_type,
            context=context,
        )
        try:
            validated = await asyncio.to_thread(
                UploadValidator(scanner=DigestBoundScanner(digest)).validate,
                content=content,
                filename=filename,
                declared_content_type=declared_content_type,
            )
        except ImageValidationError:
            await self._record(
                content=content,
                declared_media_type=declared_content_type,
                context=context,
                scan_status="malformed",
                disposition="rejected",
                error_code="IMAGE_VALIDATION_FAILED",
            )
            raise
        await self._record(
            content=content,
            declared_media_type=declared_content_type,
            context=context,
            scan_status="clean",
            disposition="accepted",
        )
        return validated

    async def validate_document(
        self,
        *,
        content: bytes,
        declared_content_type: str | None,
        context: UploadSecurityContext,
        max_bytes: int | None = None,
    ) -> str:
        if not content:
            await self._record(
                content=content,
                declared_media_type=declared_content_type,
                context=context,
                scan_status="malformed",
                disposition="rejected",
                error_code="EMPTY_UPLOAD",
            )
            raise ImageValidationError("Uploaded document is empty")
        active_limit = (
            max_bytes
            if max_bytes is not None and max_bytes > 0
            else self._settings.upload_max_file_size_bytes
        )
        if len(content) > active_limit:
            await self._record(
                content=content,
                declared_media_type=declared_content_type,
                context=context,
                scan_status="oversized",
                disposition="rejected",
                error_code="UPLOAD_TOO_LARGE",
            )
            raise ImageValidationError("Uploaded document exceeds the configured size limit")
        digest = await self._scan_original(
            content=content,
            declared_media_type=declared_content_type,
            context=context,
        )
        try:
            await asyncio.to_thread(_validate_pdf_structure, content)
        except ImageValidationError:
            await self._record(
                content=content,
                declared_media_type=declared_content_type,
                context=context,
                scan_status="malformed",
                disposition="rejected",
                error_code="PDF_VALIDATION_FAILED",
            )
            raise ImageValidationError("Uploaded document is not a readable PDF")
        await self._record(
            content=content,
            declared_media_type=declared_content_type,
            context=context,
            scan_status="clean",
            disposition="accepted",
        )
        return digest

    async def _scan_original(
        self,
        *,
        content: bytes,
        declared_media_type: str | None,
        context: UploadSecurityContext,
    ) -> str:
        digest = hashlib.sha256(content).hexdigest()
        try:
            await asyncio.to_thread(self._scanner.scan, content)
        except MalwareScanRejectedError:
            try:
                quarantine_key = await self._quarantine(content)
            except Exception:
                await self._record(
                    content=content,
                    declared_media_type=declared_media_type,
                    context=context,
                    scan_status="infected",
                    disposition="rejected",
                    detection_category="malware_detected",
                    error_code="QUARANTINE_STORAGE_FAILED",
                )
                metrics.increment("uploads.malware.quarantine_failed")
                raise MalwareScanRejectedError("Uploaded file failed security scanning") from None
            await self._record(
                content=content,
                declared_media_type=declared_media_type,
                context=context,
                scan_status="infected",
                disposition="quarantined" if quarantine_key is not None else "rejected",
                detection_category="malware_detected",
                error_code=(None if quarantine_key is not None else "QUARANTINE_DISABLED"),
                quarantine_key=quarantine_key,
            )
            metrics.increment("uploads.malware.infected")
            raise
        except MalwareScannerUnavailableError:
            await self._record(
                content=content,
                declared_media_type=declared_media_type,
                context=context,
                scan_status="scanner_error",
                disposition="rejected",
                error_code="SCANNER_UNAVAILABLE",
            )
            metrics.increment("uploads.malware.scanner_error")
            raise
        except ImageValidationError:
            await self._record(
                content=content,
                declared_media_type=declared_media_type,
                context=context,
                scan_status="scanner_error",
                disposition="rejected",
                error_code="INGESTION_DISABLED",
            )
            metrics.increment("uploads.malware.scanner_error")
            raise
        except Exception as exc:
            await self._record(
                content=content,
                declared_media_type=declared_media_type,
                context=context,
                scan_status="scanner_error",
                disposition="rejected",
                error_code="SCANNER_UNEXPECTED_FAILURE",
            )
            metrics.increment("uploads.malware.scanner_error")
            raise MalwareScannerUnavailableError(
                "Malware scanner is unavailable. Please try again later"
            ) from exc
        return digest

    async def _quarantine(self, content: bytes) -> str | None:
        if not self._settings.malware_quarantine_enabled:
            return None
        now = datetime.now(tz=UTC)
        key = f"{self._settings.malware_quarantine_prefix}/{now:%Y/%m/%d}/{uuid.uuid4()}.bin.enc"
        encrypted = _quarantine_fernet(self._settings, purpose="content").encrypt(content)
        await self._storage.upload_file(encrypted, key, "application/octet-stream")
        return key

    async def _record(
        self,
        *,
        content: bytes,
        declared_media_type: str | None,
        context: UploadSecurityContext,
        scan_status: str,
        disposition: str,
        detection_category: str | None = None,
        error_code: str | None = None,
        quarantine_key: str | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)
        locator_ciphertext = (
            _quarantine_fernet(self._settings, purpose="locator").encrypt(
                quarantine_key.encode("utf-8")
            )
            if quarantine_key is not None
            else None
        )
        record = UntrustedUploadScanModel(
            id=uuid.uuid4(),
            agency_id=context.agency_id,
            user_id=context.user_id,
            ingestion_flow=context.ingestion_flow[:64],
            content_sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
            declared_media_type=(declared_media_type or "")[:120] or None,
            scanner_name=type(self._scanner).__name__[:64],
            scanner_version=None,
            scan_status=scan_status,
            disposition=disposition,
            detection_category=detection_category,
            error_code=error_code,
            quarantine_key_ciphertext=locator_ciphertext,
            quarantine_key_version=1 if locator_ciphertext is not None else None,
            retention_expires_at=now
            + timedelta(days=self._settings.malware_quarantine_retention_days),
            created_at=now,
        )
        try:
            async with self._session_factory() as security_session:
                security_session.add(record)
                await security_session.commit()
        except Exception as exc:
            if quarantine_key is not None:
                try:
                    await self._storage.delete_files([quarantine_key])
                except Exception:
                    metrics.increment("uploads.malware.quarantine_orphans")
            raise UploadSecurityEvidenceError(
                "The upload security decision could not be recorded"
            ) from exc
        metrics.increment(f"uploads.malware.{scan_status}")


def _quarantine_fernet(settings: Settings, *, purpose: str) -> Fernet:
    key = hmac.new(
        settings.app_secret_key.encode("utf-8"),
        f"upload-quarantine:{purpose}:v1".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def decrypt_quarantine_storage_key(
    *,
    settings: Settings,
    ciphertext: bytes,
    key_version: int,
) -> str:
    if key_version != 1:
        raise QuarantineLocatorError("Unknown quarantine locator key version")
    try:
        value = _quarantine_fernet(settings, purpose="locator").decrypt(ciphertext)
        key = value.decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise QuarantineLocatorError("Quarantine locator authentication failed") from exc
    expected_prefix = settings.malware_quarantine_prefix.rstrip("/") + "/"
    if not key.startswith(expected_prefix) or "\x00" in key or len(key) > 512:
        raise QuarantineLocatorError("Quarantine locator scope is invalid")
    return key


def _validate_pdf_structure(content: bytes) -> None:
    if not content.startswith(b"%PDF-"):
        raise ImageValidationError("Uploaded document is not a readable PDF")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ImageValidationError("Encrypted documents require manual review")
        if len(reader.pages) < 1:
            raise ImageValidationError("Uploaded document contains no readable pages")
        _ = reader.pages[0].mediabox
    except ImageValidationError:
        raise
    except (PdfReadError, OSError, TypeError, ValueError, IndexError, KeyError):
        raise ImageValidationError("Uploaded document is not a readable PDF") from None


__all__ = [
    "DigestBoundScanner",
    "QuarantineLocatorError",
    "UploadSecurityContext",
    "UploadSecurityEvidenceError",
    "UploadSecurityService",
    "decrypt_quarantine_storage_key",
]
