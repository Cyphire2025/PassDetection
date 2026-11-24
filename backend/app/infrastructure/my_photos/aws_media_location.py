"""Exact-origin S3 delivery URLs bounded by their absolute authorization expiry."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import NoReturn, cast
from urllib.parse import parse_qs, unquote, urlsplit

from app.application.my_photos.errors import MyPhotosUnavailable
from app.infrastructure.my_photos.aws_provider_config import (
    AwsMyPhotosProviderConfig,
)


def _validated_presigned_media_location(
    location: object,
    *,
    config: AwsMyPhotosProviderConfig,
    media_key: str,
    expires_at: datetime,
    now: datetime,
) -> str:
    """Accept only a signed URL bound to the reviewed bucket endpoint and key."""

    if not isinstance(location, str) or len(location) > 8_192:
        _raise_invalid_delivery_location()
    try:
        parsed = urlsplit(location)
        port = parsed.port
    except ValueError:
        _raise_invalid_delivery_location()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or parsed.fragment
    ):
        _raise_invalid_delivery_location()
    try:
        decoded_path = unquote(parsed.path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        _raise_invalid_delivery_location()
    if not decoded_path.startswith("/") or "\x00" in decoded_path:
        _raise_invalid_delivery_location()

    bucket = cast(str, config.media_bucket)
    host = parsed.hostname.lower()
    candidates: set[tuple[str, str]] = set()
    if config.s3_endpoint_url is not None:
        endpoint = urlsplit(config.s3_endpoint_url)
        if endpoint.hostname is None:
            _raise_invalid_delivery_location()
        try:
            endpoint_port = endpoint.port
        except ValueError:
            _raise_invalid_delivery_location()
        if (port or 443) != (endpoint_port or 443):
            _raise_invalid_delivery_location()
        endpoint_host = endpoint.hostname.lower()
        base_path = unquote(endpoint.path, errors="strict").rstrip("/")
        if config.s3_addressing_style in {"auto", "virtual"}:
            candidates.add((f"{bucket}.{endpoint_host}", f"{base_path}/{media_key}"))
        if config.s3_addressing_style in {"auto", "path"}:
            candidates.add((endpoint_host, f"{base_path}/{bucket}/{media_key}"))
    else:
        if (port or 443) != 443:
            _raise_invalid_delivery_location()
        china_partition = config.region.startswith("cn-")
        govcloud_partition = "-gov-" in config.region
        suffix = "amazonaws.com.cn" if china_partition else "amazonaws.com"
        if config.s3_addressing_style in {"auto", "virtual"}:
            candidates.add((f"{bucket}.s3.{config.region}.{suffix}", f"/{media_key}"))
            # Botocore's ``auto`` addressing uses the legacy global virtual
            # hostname for DNS-compatible buckets in commercial AWS regions,
            # even though the client endpoint itself is regional. Keep the
            # allowlist bound to this exact bucket and official AWS hostname;
            # GovCloud and China remain regional-only.
            if config.region == "us-east-1" or (
                config.s3_addressing_style == "auto"
                and not china_partition
                and not govcloud_partition
            ):
                candidates.add((f"{bucket}.s3.{suffix}", f"/{media_key}"))
        if config.s3_addressing_style in {"auto", "path"}:
            candidates.add((f"s3.{config.region}.{suffix}", f"/{bucket}/{media_key}"))
            if config.region == "us-east-1":
                candidates.add((f"s3.{suffix}", f"/{bucket}/{media_key}"))
    if (host, decoded_path) not in candidates:
        _raise_invalid_delivery_location()
    _require_presigned_expiry(parsed.query, expires_at=expires_at, now=now)
    return location


def _require_presigned_expiry(query: str, *, expires_at: datetime, now: datetime) -> None:
    # Validate the SDK's actual SigV4 lifetime too: credentials can refresh after
    # ExpiresIn was calculated, making the signature newer than the caller's clock.
    try:
        values = parse_qs(query, keep_blank_values=True, max_num_fields=32)
        dates, lifetimes = values.get("X-Amz-Date", []), values.get("X-Amz-Expires", [])
        if len(dates) != 1 or len(lifetimes) != 1:
            _raise_invalid_delivery_location()
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", dates[0]) or not re.fullmatch(
            r"[0-9]{1,6}", lifetimes[0]
        ):
            _raise_invalid_delivery_location()
        lifetime = int(lifetimes[0])
        signed_at = datetime.strptime(dates[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        signed_expiry = signed_at + timedelta(seconds=lifetime)
    except (ValueError, OverflowError):
        _raise_invalid_delivery_location()
    if lifetime < 1 or signed_expiry > expires_at or signed_expiry <= now:
        _raise_invalid_delivery_location()


def _raise_invalid_delivery_location() -> NoReturn:
    raise MyPhotosUnavailable(
        "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Photo delivery is temporarily unavailable."
    )
