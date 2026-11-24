"""Private photo delivery provider rules."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    DeliveryAuthorization,
    DeliveryRequest,
    MediaDeliveryProvider,
)
from app.infrastructure.my_photos.delivery_policy import (
    _SUPPORTED_DELIVERY_MIME,
    _as_utc,
)
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def _authorize_provider_batch(
    *,
    provider: MediaDeliveryProvider,
    pending_calls: tuple[tuple[uuid.UUID, str, DeliveryRequest], ...],
    maximum_ttl_seconds: int,
    timeout_seconds: int,
    concurrency: int,
    maximum_batch_size: int,
) -> tuple[tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None], ...]:
    """Authorize one protocol-bounded batch with conservative concurrency.

    ``asyncio.gather`` preserves the input order. The semaphore bounds active
    provider calls, while the explicit maximum prevents this internal helper
    from ever becoming an unbounded fan-out if a future caller bypasses the API
    schema and service limit.
    """

    if not 1 <= concurrency <= 8:
        raise ValueError("Invalid delivery authorization concurrency")
    if len(pending_calls) > maximum_batch_size or not 1 <= maximum_batch_size <= 100:
        raise ValueError("Unbounded delivery authorization batch")
    semaphore = asyncio.Semaphore(concurrency)

    async def authorize_one(
        pending: tuple[uuid.UUID, str, DeliveryRequest],
    ) -> tuple[uuid.UUID, str, DeliveryAuthorization | None, str | None]:
        authorization_id, claim_token, request = pending
        async with semaphore:
            result, error_code = await _safe_provider_authorize(
                provider,
                request,
                maximum_ttl_seconds=maximum_ttl_seconds,
                timeout_seconds=timeout_seconds,
            )
        return authorization_id, claim_token, result, error_code

    return tuple(await asyncio.gather(*(authorize_one(pending) for pending in pending_calls)))


async def _safe_provider_authorize(
    provider: MediaDeliveryProvider,
    request: DeliveryRequest,
    *,
    maximum_ttl_seconds: int,
    timeout_seconds: int,
) -> tuple[DeliveryAuthorization | None, str | None]:
    try:
        async with asyncio.timeout(timeout_seconds):
            result = await provider.authorize(request)
        return (
            _validated_delivery_authorization(
                result,
                request,
                maximum_ttl_seconds=maximum_ttl_seconds,
            ),
            None,
        )
    except MyPhotosUnavailable as exc:
        return None, _stable_error_code(exc.code)
    except Exception:
        # Never persist or surface raw adapter/network errors after a durable
        # claim. The caller finalizes the claim to this stable failure category.
        my_photos_metrics.provider("unavailable")
        return None, "DELIVERY_PROVIDER_UNAVAILABLE"


def _validated_delivery_authorization(
    result: DeliveryAuthorization,
    request: DeliveryRequest,
    *,
    maximum_ttl_seconds: int,
) -> DeliveryAuthorization:
    allowed_states = {
        "registered",
        "awaiting_upload",
        "processing",
        "indexed",
        "preview_available",
        "original_available_online",
        "archived_offline",
        "rehydration_requested",
        "preparing_delivery",
        "delivery_available",
        "expired",
        "failed",
        "removed",
    }
    if result.state not in allowed_states:
        raise ValueError("Invalid media provider state")
    if result.state != "delivery_available":
        if (
            any(
                value is not None
                for value in (
                    result.provider_authorization_reference,
                    result.expected_size_bytes,
                    result.checksum_sha256,
                    result.expires_at,
                    result.content_type,
                )
            )
            or result.transport != "unavailable"
        ):
            raise ValueError("Unavailable media authorization carried delivery data")
        return result
    reference = result.provider_authorization_reference
    checksum = result.checksum_sha256
    expiry = result.expires_at
    if not (
        reference
        and len(reference) <= 512
        and reference == reference.strip()
        and reference.isprintable()
        and "://" not in reference
    ):
        raise ValueError("Invalid media provider authorization reference")
    if (
        result.expected_size_bytes != request.expected_size_bytes
        or checksum != request.checksum_sha256
        or checksum is None
        or len(checksum) != 64
        or checksum != checksum.lower()
        or any(character not in "0123456789abcdef" for character in checksum)
    ):
        raise ValueError("Media provider integrity metadata changed")
    if result.content_type not in _SUPPORTED_DELIVERY_MIME:
        raise ValueError("Invalid media provider content type")
    if result.content_type != request.content_type:
        raise ValueError("Media provider content type changed")
    if result.transport not in {"development_fixture", "direct_object_storage"}:
        raise ValueError("Invalid media provider transport")
    now = datetime.now(tz=UTC)
    if (
        expiry is None
        or _as_utc(expiry) <= now
        or _as_utc(expiry) > now + timedelta(seconds=maximum_ttl_seconds)
    ):
        raise ValueError("Expired media provider authorization")
    return result


def _stable_error_code(value: str) -> str:
    normalized = "".join(
        character if character.isascii() and (character.isalnum() or character == "_") else "_"
        for character in value.upper()
    ).strip("_")
    return (normalized or "DELIVERY_PROVIDER_UNAVAILABLE")[:64]
