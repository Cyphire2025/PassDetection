"""Signed private references and deterministic tenant/group media identities."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Mapping
from typing import Literal, cast

from app.application.my_photos.errors import MyPhotosUnavailable
from app.infrastructure.my_photos.aws_client_runtime import (
    _mapping_text,
)
from app.infrastructure.my_photos.aws_provider_config import (
    AwsMyPhotosProviderConfig,
)


class _OpaqueReferenceCodec:
    def __init__(
        self,
        active_key_id: str,
        signing_keys: Mapping[str, bytes],
        *,
        maximum_reference_length: int = 512,
    ) -> None:
        if (
            active_key_id not in signing_keys
            or len(signing_keys) > 4
            or any(len(secret) < 32 for secret in signing_keys.values())
        ):
            raise ValueError("Provider reference key ring is invalid")
        self._active_key_id = active_key_id
        self._signing_keys = dict(signing_keys)
        self._maximum_reference_length = maximum_reference_length

    def encode(self, kind: str, values: Mapping[str, object]) -> str:
        payload = {"k": kind, "v": 1, **values}
        body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = _b64url(
            hmac.new(
                self._signing_keys[self._active_key_id],
                body.encode(),
                hashlib.sha256,
            ).digest()
        )
        reference = f"aw1.{self._active_key_id}.{body}.{signature}"
        if len(reference.encode("utf-8")) > self._maximum_reference_length:
            raise ValueError("Provider reference exceeds the persistence boundary")
        return reference

    def decode(self, reference: str, kind: str) -> dict[str, object]:
        if (
            not isinstance(reference, str)
            or len(reference.encode("utf-8")) > self._maximum_reference_length
        ):
            raise ValueError("Invalid opaque provider reference")
        try:
            prefix, key_id, body, signature = reference.split(".", 3)
            secret = self._signing_keys.get(key_id)
            if secret is None:
                raise ValueError
            expected = _b64url(hmac.new(secret, body.encode(), hashlib.sha256).digest())
            if prefix != "aw1" or not hmac.compare_digest(signature, expected):
                raise ValueError
            decoded = json.loads(_b64url_decode(body))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid opaque provider reference") from exc
        if not isinstance(decoded, dict) or decoded.get("v") != 1 or decoded.get("k") != kind:
            raise ValueError("Invalid opaque provider reference")
        return cast(dict[str, object], decoded)


def media_object_reference(
    config: AwsMyPhotosProviderConfig,
    *,
    tenant_scope: str,
    group_scope: str,
    asset_identity: str,
    variant: Literal["thumbnail", "preview", "analysis", "original", "optimized"],
) -> str:
    tenant = _canonical_uuid_scope(tenant_scope)
    group = _canonical_uuid_scope(group_scope)
    scope = _hmac_hex(config.scope_hmac_secret, f"media|{tenant}|{group}")[:48]
    asset = hashlib.sha256(asset_identity.encode("utf-8")).hexdigest()
    reference = f"{config.media_key_prefix}/{scope}/{asset}/{variant}"
    if len(reference) > 512:
        raise ValueError("Media object reference exceeds the persistence boundary")
    return reference


def _require_scoped_media_reference(
    config: AwsMyPhotosProviderConfig,
    reference: str,
    *,
    tenant_scope: str,
    group_scope: str,
) -> None:
    tenant = _canonical_uuid_scope(tenant_scope)
    group = _canonical_uuid_scope(group_scope)
    scope = _hmac_hex(config.scope_hmac_secret, f"media|{tenant}|{group}")[:48]
    prefix = f"{config.media_key_prefix}/{scope}/"
    if (
        not reference.startswith(prefix)
        or len(reference) > 512
        or reference != reference.strip()
        or not reference.isprintable()
        or "//" in reference
        or any(part in {"", ".", ".."} for part in reference.split("/"))
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_SCOPE_INVALID", "Photo storage reference is invalid."
        )


def _encode_versioned_media_reference(
    codec: _OpaqueReferenceCodec,
    media_key: str,
    version_id: str,
) -> str:
    if not _valid_s3_version_id(version_id):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_VERSION_INVALID", "Photo storage version is invalid."
        )
    try:
        return codec.encode("mo", {"n": media_key, "o": version_id})
    except ValueError as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_VERSION_INVALID", "Photo storage version is invalid."
        ) from exc


def _decode_versioned_media_reference(
    codec: _OpaqueReferenceCodec,
    reference: str,
    *,
    config: AwsMyPhotosProviderConfig,
    tenant_scope: str,
    group_scope: str,
) -> tuple[str, str]:
    decoded = codec.decode(reference, "mo")
    media_key = _mapping_text(decoded, "n", maximum=512)
    version_id = _mapping_text(decoded, "o", maximum=1_024)
    if not _valid_s3_version_id(version_id):
        raise ValueError("Invalid media object version")
    _require_scoped_media_reference(
        config,
        media_key,
        tenant_scope=tenant_scope,
        group_scope=group_scope,
    )
    return media_key, version_id


def _valid_s3_version_id(value: object) -> bool:
    if not isinstance(value, str) or value == "null" or value != value.strip():
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return 1 <= len(encoded) <= 1_024 and value.isprintable()


def _delivery_fingerprint(
    tenant_scope: str,
    group_scope: str,
    passenger_scope: str,
    authorization_identity: str,
    asset_identity: str,
    media_reference: str,
    quality: str,
    expected_size_bytes: int,
    checksum_sha256: str,
    content_type: str,
) -> str:
    values = (
        _canonical_uuid_scope(tenant_scope),
        _canonical_uuid_scope(group_scope),
        _canonical_uuid_scope(passenger_scope),
        authorization_identity,
        asset_identity,
        media_reference,
        quality,
        str(expected_size_bytes),
        checksum_sha256,
        content_type,
    )
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def _canonical_uuid_scope(value: str) -> str:
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Provider scope must be a canonical UUID") from exc
    if value.lower() != normalized:
        raise ValueError("Provider scope must be a canonical UUID")
    return normalized


def _aws_idempotency_token(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]", "-", value)[:64]
    if 1 <= len(normalized) <= 64 and normalized == value:
        return normalized
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hmac_hex(secret: bytes, value: str) -> str:
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))
