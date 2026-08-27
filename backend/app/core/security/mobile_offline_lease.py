"""Asymmetric, device-bound authorization leases for the GC mobile offline shell.

The compact format intentionally follows the signed portion of JWS while keeping
the accepted header and claim sets much smaller than a general JWT profile.  The
mobile app pins only Ed25519 public keys; the private key is backend-only.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Literal, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

if TYPE_CHECKING:
    from app.core.config.settings import MobileSettings


OFFLINE_LEASE_ALGORITHM = "EdDSA"
OFFLINE_LEASE_TYPE = "GC-OFFLINE-AUTH"
OFFLINE_LEASE_FORMAT_VERSION = 1
MAX_OFFLINE_LEASE_VERIFICATION_KEYS = 5
MAX_SIGNED_OFFLINE_MANIFEST_BYTES = 2 * 1024 * 1024

_KID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_INSTALLATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


class MobileOfflineLeaseConfigurationError(ValueError):
    """Raised without including any private signing material."""


@dataclass(frozen=True, slots=True)
class _SigningMaterial:
    active_kid: str
    private_key: Ed25519PrivateKey
    verification_keys: dict[str, Ed25519PublicKey]


@dataclass(frozen=True, slots=True)
class SignedOfflineManifest:
    """Canonical Ed25519 envelope for an authenticated offline manifest."""

    key_id: str
    payload: str
    public_key: str
    signature: str


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_base64url(value: str, *, label: str, max_encoded_length: int) -> bytes:
    if not value or len(value) > max_encoded_length or not _BASE64URL_PATTERN.fullmatch(value):
        raise MobileOfflineLeaseConfigurationError(f"{label} is not canonical base64url")
    try:
        decoded = base64.b64decode(
            value + ("=" * (-len(value) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise MobileOfflineLeaseConfigurationError(f"{label} is not canonical base64url") from exc
    if _encode_base64url(decoded) != value:
        raise MobileOfflineLeaseConfigurationError(f"{label} is not canonical base64url")
    return decoded


def _strict_json_object(value: str) -> dict[str, object]:
    if not value or len(value) > 8_192:
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON is missing or too large"
        )

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise MobileOfflineLeaseConfigurationError(
                    "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON contains duplicate key ids"
                )
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=reject_duplicate_keys)
    except MobileOfflineLeaseConfigurationError:
        raise
    except (TypeError, ValueError) as exc:
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON must be a JSON object"
        ) from exc
    if not isinstance(parsed, dict):
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON must be a JSON object"
        )
    return parsed


def _load_signing_material_uncached(
    active_kid: str,
    private_key_b64: str,
    public_keys_json: str,
) -> _SigningMaterial:
    if not _KID_PATTERN.fullmatch(active_kid):
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_ACTIVE_KID has an invalid format"
        )

    parsed_keys = _strict_json_object(public_keys_json)
    if not 1 <= len(parsed_keys) <= MAX_OFFLINE_LEASE_VERIFICATION_KEYS:
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON must contain between 1 and 5 keys"
        )

    verification_keys: dict[str, Ed25519PublicKey] = {}
    raw_verification_keys: dict[str, bytes] = {}
    for kid, encoded_key in parsed_keys.items():
        if not _KID_PATTERN.fullmatch(kid):
            raise MobileOfflineLeaseConfigurationError(
                "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON contains an invalid key id"
            )
        if not isinstance(encoded_key, str):
            raise MobileOfflineLeaseConfigurationError(
                "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON values must be base64url strings"
            )
        raw_key = _decode_base64url(
            encoded_key,
            label="MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON key",
            max_encoded_length=64,
        )
        if len(raw_key) != 32:
            raise MobileOfflineLeaseConfigurationError(
                "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON keys must be 32-byte Ed25519 keys"
            )
        try:
            verification_keys[kid] = Ed25519PublicKey.from_public_bytes(raw_key)
        except ValueError as exc:
            raise MobileOfflineLeaseConfigurationError(
                "MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON contains an invalid Ed25519 key"
            ) from exc
        raw_verification_keys[kid] = raw_key

    if active_kid not in verification_keys:
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_ACTIVE_KID is not present in the verification key set"
        )

    private_der = _decode_base64url(
        private_key_b64,
        label="MOBILE_OFFLINE_LEASE_PRIVATE_KEY_B64",
        max_encoded_length=2_048,
    )
    try:
        loaded_private_key = serialization.load_der_private_key(
            private_der,
            password=None,
        )
    except (TypeError, ValueError) as exc:
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_PRIVATE_KEY_B64 is not a valid PKCS8 Ed25519 key"
        ) from exc
    if not isinstance(loaded_private_key, Ed25519PrivateKey):
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_PRIVATE_KEY_B64 must contain an Ed25519 private key"
        )

    active_public = loaded_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    if active_public != raw_verification_keys[active_kid]:
        raise MobileOfflineLeaseConfigurationError(
            "The active offline lease private key does not match its verification key"
        )
    return _SigningMaterial(
        active_kid=active_kid,
        private_key=loaded_private_key,
        verification_keys=verification_keys,
    )


@lru_cache(maxsize=8)
def _load_signing_material(
    active_kid: str,
    private_key_b64: str,
    public_keys_json: str,
) -> _SigningMaterial:
    return _load_signing_material_uncached(
        active_kid,
        private_key_b64,
        public_keys_json,
    )


def validate_mobile_offline_lease_signing_configuration(
    *,
    active_kid: str | None,
    private_key_b64: str | None,
    public_keys_json: str | None,
) -> None:
    """Validate key type, key-set bounds, active kid, and private/public match."""

    if not active_kid or not private_key_b64 or not public_keys_json:
        raise MobileOfflineLeaseConfigurationError(
            "MOBILE_OFFLINE_LEASE_ACTIVE_KID, MOBILE_OFFLINE_LEASE_PRIVATE_KEY_B64, "
            "and MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON are required"
        )
    _load_signing_material(active_kid, private_key_b64, public_keys_json)


def _settings_signing_material(settings: MobileSettings) -> _SigningMaterial:
    private_secret = settings.offline_lease_private_key_b64
    private_key_b64 = (
        private_secret.get_secret_value().strip() if private_secret is not None else ""
    )
    active_kid = settings.offline_lease_active_kid or ""
    public_keys_json = settings.offline_lease_public_keys_json or ""
    validate_mobile_offline_lease_signing_configuration(
        active_kid=active_kid,
        private_key_b64=private_key_b64,
        public_keys_json=public_keys_json,
    )
    return _load_signing_material(active_kid, private_key_b64, public_keys_json)


def create_mobile_offline_authorization_lease(
    *,
    principal_id: uuid.UUID,
    account_id: uuid.UUID,
    principal_type: Literal["passenger", "client_manager", "coordinator"] | str,
    agency_id: uuid.UUID,
    passenger_id: uuid.UUID | None,
    session_id: uuid.UUID,
    session_generation: int,
    installation_id: str,
    principal_generation: int | None,
    access_generation: int | None,
    now: datetime | None = None,
    settings: MobileSettings | None = None,
) -> str:
    """Issue one bounded Ed25519 authorization lease without embedding PII or tokens."""

    if settings is None:
        # Local import avoids a settings/security import cycle during startup validation.
        from app.core.config.settings import get_settings

        settings = get_settings().mobile
    material = _settings_signing_material(settings)

    if principal_type not in {"passenger", "client_manager", "coordinator"}:
        raise ValueError("Unsupported mobile principal type")
    if not _INSTALLATION_PATTERN.fullmatch(installation_id):
        raise ValueError("Invalid mobile installation identity")
    if session_generation < 1:
        raise ValueError("Invalid mobile session generation")
    if principal_generation is not None and principal_generation < 0:
        raise ValueError("Invalid mobile principal generation")
    if access_generation is not None and access_generation < 0:
        raise ValueError("Invalid mobile access generation")

    issued_at = now or datetime.now(tz=UTC)
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("Offline authorization lease time must be timezone-aware")
    issued_at_seconds = int(issued_at.timestamp())
    expires_at_seconds = issued_at_seconds + (settings.offline_lease_ttl_minutes * 60)

    header: dict[str, object] = {
        "alg": OFFLINE_LEASE_ALGORITHM,
        "kid": material.active_kid,
        "typ": OFFLINE_LEASE_TYPE,
        "v": OFFLINE_LEASE_FORMAT_VERSION,
    }
    payload: dict[str, object] = {
        "access_generation": access_generation,
        "account_id": str(account_id),
        "agency_id": str(agency_id),
        "aud": settings.offline_lease_audience,
        "exp": expires_at_seconds,
        "format_version": OFFLINE_LEASE_FORMAT_VERSION,
        "iat": issued_at_seconds,
        "installation_id": installation_id,
        "iss": settings.offline_lease_issuer,
        "jti": str(uuid.uuid4()),
        "nbf": issued_at_seconds,
        "passenger_id": str(passenger_id) if passenger_id is not None else None,
        "principal_generation": principal_generation,
        "principal_type": principal_type,
        "server_time": issued_at_seconds,
        "session_generation": session_generation,
        "session_id": str(session_id),
        "sub": str(principal_id),
    }
    encoded_header = _encode_base64url(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("ascii")
    )
    encoded_payload = _encode_base64url(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")
    )
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = material.private_key.sign(signing_input)
    return f"{encoded_header}.{encoded_payload}.{_encode_base64url(signature)}"


def sign_offline_manifest(
    payload: Mapping[str, object],
    *,
    settings: MobileSettings | None = None,
) -> SignedOfflineManifest:
    """Sign a bounded canonical JSON manifest with the offline lease key.

    The returned envelope intentionally contains the active public key so a
    browser can import it as non-exportable key material after authenticated
    HTTPS provisioning. Clients must pin the key id and digest and reject a
    different key for an already observed id.
    """

    if settings is None:
        from app.core.config.settings import get_settings

        settings = get_settings().mobile
    material = _settings_signing_material(settings)
    if payload.get("key_id") != material.active_kid:
        raise ValueError("Offline manifest key id does not match the active signing key")
    payload_bytes = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if not 1 <= len(payload_bytes) <= MAX_SIGNED_OFFLINE_MANIFEST_BYTES:
        raise ValueError("Offline manifest exceeds the supported size")
    public_key = material.verification_keys[material.active_kid].public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return SignedOfflineManifest(
        key_id=material.active_kid,
        payload=_encode_base64url(payload_bytes),
        public_key=_encode_base64url(public_key),
        signature=_encode_base64url(material.private_key.sign(payload_bytes)),
    )


__all__ = [
    "MAX_OFFLINE_LEASE_VERIFICATION_KEYS",
    "MAX_SIGNED_OFFLINE_MANIFEST_BYTES",
    "MobileOfflineLeaseConfigurationError",
    "SignedOfflineManifest",
    "create_mobile_offline_authorization_lease",
    "sign_offline_manifest",
    "validate_mobile_offline_lease_signing_configuration",
]
