"""Passport public security: focused workflow boundary."""

from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

from app.core.config.settings import get_settings
from app.core.security.upload_session import upload_session_matches_identifier
from app.domain.exceptions.exceptions import PassDetectionError
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.security.upload_security import (
    UploadSecurityContext,
    UploadSecurityEvidenceError,
    UploadSecurityService,
)
from app.infrastructure.security.upload_validator import (
    MalwareScannerUnavailableError,
    ValidatedUpload,
)


def _require_public_upload_credential(
    submission: object,
    upload_session_id: str,
) -> None:
    """Require a per-upload capability that is independent of the public UUID."""

    expected = getattr(submission, "upload_idempotency_key", None)
    if not isinstance(expected, str) or not upload_session_matches_identifier(
        upload_session_id,
        expected,
    ):
        # Use the same response as an unknown submission so this check does
        # not become a capability-validation oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport submission was not found",
        )


async def _read_upload_content(file: UploadFile, *, label: str, limit: int) -> bytes:
    """Bound multipart reads and release their temporary files on every path."""
    try:
        return await file.read(limit + 1)
    except Exception:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "read_error",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read {label} file content",
        )
    finally:
        try:
            await file.close()
        except Exception:
            # Request teardown retains ownership of a failed multipart close.
            pass


def _require_upload_size(
    content: bytes, *, label: str, limit: int, max_size_bytes: int | None,
) -> None:
    if len(content) > limit:
        record_operational_event(OperationalEvent.UPLOAD_RESULT, "validation_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The {label} file must be 2 MB or smaller." if max_size_bytes else f"The {label} file exceeds the upload size limit.",
        )


async def _validated_upload_file(
    file: UploadFile, *, label: str, max_size_bytes: int | None = None,
) -> ValidatedUpload:
    limit = get_settings().upload_max_file_size_bytes
    if max_size_bytes is not None:
        limit = min(limit, max_size_bytes)
    filename = file.filename
    content_type = file.content_type
    content = await _read_upload_content(file, label=label, limit=limit)
    _require_upload_size(content, label=label, limit=limit, max_size_bytes=max_size_bytes)
    try:
        return await UploadSecurityService().validate_image(
            content=content,
            filename=filename,
            declared_content_type=content_type,
            context=UploadSecurityContext(ingestion_flow="public_passport_upload"),
        )
    except (MalwareScannerUnavailableError, UploadSecurityEvidenceError) as exc:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "security_scanner_unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document security scanning is temporarily unavailable",
            headers={"Retry-After": "30"},
        ) from exc
    except PassDetectionError as exc:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "validation_failed",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
