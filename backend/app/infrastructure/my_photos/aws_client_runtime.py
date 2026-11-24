"""AWS client dispatch and closed error projections shared by photo adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from app.application.my_photos.errors import MyPhotosUnavailable
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations

_THROTTLE_CODES = {
    "ThrottlingException",
    "ProvisionedThroughputExceededException",
    "SlowDown",
    "TooManyRequestsException",
}


_NOT_FOUND_CODES = {
    "404",
    "NoSuchKey",
    "NotFound",
    "ResourceNotFoundException",
    "SessionNotFoundException",
}


async def _async_client_call(method: Callable[..., Any], *args: object, **kwargs: object) -> Any:
    results = await run_bounded_storage_operations(
        [lambda: asyncio.to_thread(method, *args, **kwargs)], concurrency=1
    )
    return results[0]


def _client_error_code(exc: ClientError) -> str:
    error = exc.response.get("Error", {})
    return (
        str(error.get("Code", "ProviderError")) if isinstance(error, Mapping) else "ProviderError"
    )


def _raise_provider_failure(exc: ClientError, *, operation: str) -> None:
    code = _client_error_code(exc)
    if code in _THROTTLE_CODES:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_THROTTLED", f"{operation} is busy. Try again shortly."
        ) from None
    raise MyPhotosUnavailable(
        "MY_PHOTOS_PROVIDER_UNAVAILABLE", f"{operation} is temporarily unavailable."
    ) from None


def _required_text(response: Mapping[str, object], key: str, *, maximum: int) -> str:
    value = response.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum or not value.isprintable():
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Provider response is temporarily unavailable."
        )
    return value


def _mapping_text(response: Mapping[str, object], key: str, *, maximum: int) -> str:
    value = response.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum or not value.isprintable():
        raise ValueError("Opaque reference value is invalid")
    return value


def _mapping_epoch(response: Mapping[str, object], key: str) -> datetime:
    value = response.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Opaque reference expiry is invalid")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("Opaque reference expiry is invalid") from exc


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
