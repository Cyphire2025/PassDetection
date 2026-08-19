"""PII-free request binding contracts for mobile platform attestation.

This module deliberately contains no provider cryptography. Google decrypts and
verifies Play Integrity tokens server-to-server; an audited Apple verifier must
validate App Attest objects before returning public verification material.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

MobileIntegrityProvider = Literal["play_integrity", "app_attest"]
MobileIntegrityAction = Literal[
    "document_download_authorize",
    "app_attest_key_register",
]

INTEGRITY_BINDING_VERSION = 1
INTEGRITY_DIGEST_PATTERN = r"^[A-Za-z0-9_-]{43}$"


class MobileIntegrityUnavailable(RuntimeError):
    """The server cannot obtain an authoritative provider verdict."""


class MobileIntegrityRejected(RuntimeError):
    """An authoritative provider or server binding rejected the proof."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class MobileIntegrityChallenge:
    challenge_id: uuid.UUID
    provider: MobileIntegrityProvider
    action: MobileIntegrityAction
    request_hash: str
    provider_request_hash: str
    agency_binding: str
    account_binding: str
    session_binding: str
    installation_binding: str
    key_binding: str | None
    expires_at_epoch: int

    def to_json(self) -> str:
        payload = asdict(self)
        payload["challenge_id"] = str(self.challenge_id)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, encoded: str) -> MobileIntegrityChallenge:
        if len(encoded) > 4_096:
            raise ValueError("Integrity challenge record is oversized")
        payload: object = json.loads(encoded)
        if not isinstance(payload, dict) or set(payload) != {
            "challenge_id",
            "provider",
            "action",
            "request_hash",
            "provider_request_hash",
            "agency_binding",
            "account_binding",
            "session_binding",
            "installation_binding",
            "key_binding",
            "expires_at_epoch",
        }:
            raise ValueError("Integrity challenge record has an invalid shape")
        provider = payload["provider"]
        action = payload["action"]
        if provider not in {"play_integrity", "app_attest"}:
            raise ValueError("Integrity challenge provider is invalid")
        if action not in {"document_download_authorize", "app_attest_key_register"}:
            raise ValueError("Integrity challenge action is invalid")
        string_fields = (
            "request_hash",
            "provider_request_hash",
            "agency_binding",
            "account_binding",
            "session_binding",
            "installation_binding",
        )
        if any(
            not isinstance(payload[field], str)
            or len(payload[field]) != 43
            or not _is_base64url_digest(payload[field])
            for field in string_fields
        ):
            raise ValueError("Integrity challenge digest is invalid")
        key_binding = payload["key_binding"]
        if key_binding is not None and (
            not isinstance(key_binding, str)
            or len(key_binding) != 43
            or not _is_base64url_digest(key_binding)
        ):
            raise ValueError("Integrity challenge key binding is invalid")
        expires_at_epoch = payload["expires_at_epoch"]
        if (
            not isinstance(expires_at_epoch, int)
            or isinstance(expires_at_epoch, bool)
            or expires_at_epoch < 0
        ):
            raise ValueError("Integrity challenge expiry is invalid")
        return cls(
            challenge_id=uuid.UUID(str(payload["challenge_id"])),
            provider=provider,
            action=action,
            request_hash=payload["request_hash"],
            provider_request_hash=payload["provider_request_hash"],
            agency_binding=payload["agency_binding"],
            account_binding=payload["account_binding"],
            session_binding=payload["session_binding"],
            installation_binding=payload["installation_binding"],
            key_binding=key_binding,
            expires_at_epoch=expires_at_epoch,
        )


@dataclass(frozen=True, slots=True)
class AppleAppAttestRegistrationVerdict:
    verification_material: bytes
    counter: int
    environment: Literal["development", "production"]


@dataclass(frozen=True, slots=True)
class AppleAppAttestAssertionVerdict:
    counter: int


class AppleAppAttestVerifier(Protocol):
    async def verify_attestation(
        self,
        *,
        attestation_object: str,
        key_id: str,
        server_challenge: str,
        app_id: str,
        environment: Literal["development", "production"],
    ) -> AppleAppAttestRegistrationVerdict: ...

    async def verify_assertion(
        self,
        *,
        assertion_object: str,
        key_id: str,
        client_data: str,
        app_id: str,
        verification_material: bytes,
        previous_counter: int,
    ) -> AppleAppAttestAssertionVerdict: ...


def mobile_document_authorization_request_hash(
    *,
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    version: int,
) -> str:
    if version < 1:
        raise ValueError("Document version must be positive")
    return _sha256_base64url(
        (
            f"gc-mobile-integrity-v1\0document_download_authorize\0"
            f"{group_id}\0{document_id}\0{version}"
        ).encode("ascii")
    )


def app_attest_key_registration_request_hash(*, key_id: str) -> str:
    if not 32 <= len(key_id) <= 512:
        raise ValueError("App Attest key identifier is outside the bounded contract")
    return _sha256_base64url(
        f"gc-mobile-integrity-v1\0app_attest_key_register\0{key_id}".encode("ascii")
    )


def create_mobile_integrity_challenge(
    *,
    provider: MobileIntegrityProvider,
    action: MobileIntegrityAction,
    request_hash: str,
    agency_id: uuid.UUID,
    account_id: uuid.UUID,
    session_id: uuid.UUID,
    device_identifier_hash: str,
    key_id: str | None,
    binding_secret: bytes,
    ttl_seconds: int,
    now: datetime | None = None,
) -> MobileIntegrityChallenge:
    if not _is_base64url_digest(request_hash):
        raise ValueError("Integrity request hash must be a SHA-256 base64url digest")
    if re.fullmatch(r"[0-9a-f]{64}", device_identifier_hash) is None:
        raise ValueError("Integrity installation binding is invalid")
    if action == "app_attest_key_register" and (provider != "app_attest" or not key_id):
        raise ValueError("App Attest key registration requires an Apple key identifier")
    if action != "app_attest_key_register" and key_id is None and provider == "app_attest":
        raise ValueError("App Attest assertions require a registered key identifier")
    if provider == "play_integrity" and key_id is not None:
        raise ValueError("Play Integrity does not accept an App Attest key identifier")
    if not 30 <= ttl_seconds <= 300:
        raise ValueError("Integrity challenge TTL is outside the bounded policy")

    issued_at = now or datetime.now(tz=UTC)
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("Integrity challenge time must be timezone-aware")
    challenge_id = uuid.uuid4()
    agency_binding = _hmac_binding(binding_secret, "agency", str(agency_id))
    account_binding = _hmac_binding(binding_secret, "account", str(account_id))
    session_binding = _hmac_binding(binding_secret, "session", str(session_id))
    installation_binding = _sha256_base64url(device_identifier_hash.encode("ascii"))
    key_binding = (
        _hmac_binding(binding_secret, "app-attest-key", key_id) if key_id else None
    )
    provider_payload = {
        "v": INTEGRITY_BINDING_VERSION,
        "challenge_id": str(challenge_id),
        "provider": provider,
        "action": action,
        "request_hash": request_hash,
        "agency": agency_binding,
        "account": account_binding,
        "session": session_binding,
        "installation": installation_binding,
        "key": key_binding,
    }
    provider_request_hash = _sha256_base64url(
        json.dumps(provider_payload, separators=(",", ":"), sort_keys=True).encode("ascii")
    )
    return MobileIntegrityChallenge(
        challenge_id=challenge_id,
        provider=provider,
        action=action,
        request_hash=request_hash,
        provider_request_hash=provider_request_hash,
        agency_binding=agency_binding,
        account_binding=account_binding,
        session_binding=session_binding,
        installation_binding=installation_binding,
        key_binding=key_binding,
        expires_at_epoch=int(issued_at.timestamp()) + ttl_seconds,
    )


def validate_mobile_integrity_challenge(
    challenge: MobileIntegrityChallenge,
    *,
    provider: MobileIntegrityProvider,
    action: MobileIntegrityAction,
    request_hash: str,
    agency_id: uuid.UUID,
    account_id: uuid.UUID,
    session_id: uuid.UUID,
    device_identifier_hash: str,
    key_id: str | None,
    binding_secret: bytes,
    now: datetime | None = None,
) -> None:
    checked_at = now or datetime.now(tz=UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("Integrity challenge time must be timezone-aware")
    expected = {
        "provider": provider,
        "action": action,
        "request_hash": request_hash,
        "agency": _hmac_binding(binding_secret, "agency", str(agency_id)),
        "account": _hmac_binding(binding_secret, "account", str(account_id)),
        "session": _hmac_binding(binding_secret, "session", str(session_id)),
        "installation": _sha256_base64url(device_identifier_hash.encode("ascii")),
        "key": _hmac_binding(binding_secret, "app-attest-key", key_id) if key_id else None,
    }
    actual = {
        "provider": challenge.provider,
        "action": challenge.action,
        "request_hash": challenge.request_hash,
        "agency": challenge.agency_binding,
        "account": challenge.account_binding,
        "session": challenge.session_binding,
        "installation": challenge.installation_binding,
        "key": challenge.key_binding,
    }
    for field, expected_value in expected.items():
        actual_value = actual[field]
        if actual_value is None or expected_value is None:
            matches = actual_value is expected_value
        else:
            matches = hmac.compare_digest(str(actual_value), str(expected_value))
        if not matches:
            raise MobileIntegrityRejected(f"binding_{field}")
    if int(checked_at.timestamp()) >= challenge.expires_at_epoch:
        raise MobileIntegrityRejected("challenge_expired")


def _hmac_binding(secret: bytes, purpose: str, value: str | None) -> str:
    if not secret or value is None:
        raise ValueError("Integrity binding input is missing")
    digest = hmac.new(
        secret,
        f"mobile-integrity-v1\0{purpose}\0{value}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _base64url(digest)


def _sha256_base64url(value: bytes) -> str:
    return _base64url(hashlib.sha256(value).digest())


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _is_base64url_digest(value: object) -> bool:
    if (
        not isinstance(value, str)
        or re.fullmatch(INTEGRITY_DIGEST_PATTERN, value) is None
    ):
        return False
    try:
        return len(base64.urlsafe_b64decode(value + "=")) == 32
    except (ValueError, TypeError):
        return False


__all__ = [
    "AppleAppAttestAssertionVerdict",
    "AppleAppAttestRegistrationVerdict",
    "AppleAppAttestVerifier",
    "MobileIntegrityAction",
    "MobileIntegrityChallenge",
    "MobileIntegrityProvider",
    "MobileIntegrityRejected",
    "MobileIntegrityUnavailable",
    "create_mobile_integrity_challenge",
    "mobile_document_authorization_request_hash",
    "validate_mobile_integrity_challenge",
    "app_attest_key_registration_request_hash",
]
