"""Validation and claim-state helpers for My Photos liveness providers."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

from app.application.my_photos.errors import MyPhotosRateLimited
from app.application.my_photos.providers import LivenessResult, LivenessSessionHandle
from app.infrastructure.database.my_photos_models import MyPhotoLivenessSessionModel


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _provider_claim_active(
    session: MyPhotoLivenessSessionModel,
    now: datetime,
) -> bool:
    return (
        session.provider_claim_token is not None
        and session.provider_claim_expires_at is not None
        and _as_utc(session.provider_claim_expires_at) > now
    )


def _liveness_processing(
    session: MyPhotoLivenessSessionModel,
    now: datetime,
) -> MyPhotosRateLimited:
    claim_expiry = session.provider_claim_expires_at
    retry_after = (
        math.ceil((_as_utc(claim_expiry) - now).total_seconds()) if claim_expiry is not None else 1
    )
    return MyPhotosRateLimited(
        retry_after,
        "Face Scan is being processed. Try again shortly.",
        code="MY_PHOTOS_SESSION_PROCESSING",
    )


def _validated_liveness_session_handle(
    handle: LivenessSessionHandle,
    *,
    requested_expiry: datetime,
    client_flow: Literal["development_simulator", "native"],
) -> LivenessSessionHandle:
    if not _valid_opaque_provider_value(handle.provider_reference, maximum=512):
        raise ValueError("Invalid liveness provider session handle")
    now = datetime.now(tz=UTC)
    expiry = _as_utc(handle.expires_at)
    if expiry <= now or expiry > _as_utc(requested_expiry):
        raise ValueError("Invalid liveness provider session expiry")
    native_handle = handle.native_launch_handle
    if client_flow == "native":
        if native_handle is None or not _valid_opaque_provider_value(native_handle, maximum=512):
            raise ValueError("Invalid native liveness launch handle")
    elif native_handle is not None:
        raise ValueError("Development liveness cannot expose native launch data")
    return handle


def _validated_liveness_result(result: LivenessResult) -> LivenessResult:
    allowed = {
        "passed",
        "rejected",
        "expired",
        "throttled",
        "unavailable",
        "no_face",
        "multiple_faces",
        "failed",
    }
    if result.outcome not in allowed:
        raise ValueError("Invalid liveness provider outcome")
    if result.outcome == "passed":
        if not _valid_opaque_provider_value(result.reference_face_handle, maximum=4_096):
            raise ValueError("Passed liveness result requires one bounded reference")
        if result.stable_error_code is not None:
            raise ValueError("Passed liveness result cannot include an error")
    elif result.reference_face_handle is not None:
        raise ValueError("Rejected liveness result cannot include a reference")
    if result.stable_error_code is not None and (
        len(result.stable_error_code) > 64
        or result.stable_error_code != result.stable_error_code.strip()
        or not result.stable_error_code.replace("_", "").isalnum()
    ):
        raise ValueError("Invalid liveness provider error category")
    return result


def _valid_opaque_provider_value(value: str | None, *, maximum: int) -> bool:
    return bool(
        value
        and len(value) <= maximum
        and value == value.strip()
        and value.isprintable()
        and "://" not in value
    )
