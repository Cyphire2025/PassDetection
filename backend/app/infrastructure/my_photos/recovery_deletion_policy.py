"""Reference identity fences and bounded retry/deletion state policy."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import MyPhotoEnrollmentModel
from app.infrastructure.my_photos.recovery_contracts import DeletionKind, _DeletionClaim


def _reference_unchanged(enrollment: MyPhotoEnrollmentModel, claim: _DeletionClaim) -> bool:
    if claim.kind == "superseded":
        return bool(
            enrollment.superseded_provider_reference_handle == claim.provider_reference
            and enrollment.superseded_deletion_attempt_count == claim.attempt_count
        )
    return bool(
        enrollment.status == "deleted"
        and enrollment.provider_reference_handle == claim.provider_reference
        and enrollment.deletion_idempotency_key == claim.deletion_identity
        and enrollment.provider_deletion_attempt_count == claim.attempt_count
    )


def _complete_reference(
    enrollment: MyPhotoEnrollmentModel, kind: DeletionKind, now: datetime
) -> None:
    if kind == "superseded":
        enrollment.superseded_provider_reference_handle = None
        enrollment.superseded_reference_deletion_status = "complete"
        enrollment.superseded_reference_deletion_error_code = None
        enrollment.superseded_reference_deletion_completed_at = now
        enrollment.superseded_deletion_attempt_count = 0
        enrollment.superseded_deletion_next_attempt_at = None
    else:
        enrollment.provider_name = None
        enrollment.provider_reference_handle = None
        enrollment.provider_deletion_status = "complete"
        enrollment.provider_deletion_error_code = None
        enrollment.provider_deletion_completed_at = now
        enrollment.provider_deletion_next_attempt_at = None


def _pending_reference(
    enrollment: MyPhotoEnrollmentModel,
    kind: DeletionKind,
    error_code: str | None,
) -> None:
    if kind == "superseded":
        enrollment.superseded_reference_deletion_status = "pending"
        enrollment.superseded_reference_deletion_error_code = error_code
    else:
        enrollment.provider_deletion_status = "pending"
        enrollment.provider_deletion_error_code = error_code


def _fail_reference(
    enrollment: MyPhotoEnrollmentModel,
    kind: DeletionKind,
    error_code: str | None,
) -> None:
    stable = error_code or "PROVIDER_DELETION_UNAVAILABLE"
    if kind == "superseded":
        enrollment.superseded_reference_deletion_status = "failed"
        enrollment.superseded_reference_deletion_error_code = stable
    else:
        enrollment.provider_deletion_status = "failed"
        enrollment.provider_deletion_error_code = stable


def _deletion_retry_delay(claim: _DeletionClaim, settings: Settings) -> int:
    base = min(
        settings.my_photos.job_retry_max_seconds,
        settings.my_photos.job_retry_base_seconds * (2 ** min(max(claim.attempt_count - 1, 0), 8)),
    )
    digest = hashlib.sha256(
        f"{claim.enrollment_id}:{claim.kind}:{claim.attempt_count}".encode("ascii")
    ).digest()
    jitter = int.from_bytes(digest[:2], "big") % max(1, base // 2 + 1)
    return int(min(settings.my_photos.job_retry_max_seconds, base + jitter))


def _set_next_attempt(
    enrollment: MyPhotoEnrollmentModel,
    kind: DeletionKind,
    value: datetime | None,
) -> None:
    if kind == "superseded":
        enrollment.superseded_deletion_next_attempt_at = value
    else:
        enrollment.provider_deletion_next_attempt_at = value


def _due(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return True
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized <= now


def _stable_error(value: str) -> str:
    normalized = "".join(
        character if character.isascii() and (character.isalnum() or character == "_") else "_"
        for character in value.upper()
    )
    return normalized[:64] or "PROVIDER_DELETION_UNAVAILABLE"


_reference_unchanged.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_complete_reference.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_pending_reference.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_fail_reference.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_deletion_retry_delay.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_set_next_attempt.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_due.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_stable_error.__module__ = "app.infrastructure.my_photos.recovery_runtime"
