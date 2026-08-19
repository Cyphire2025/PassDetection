from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.core.config.settings import MobileSettings
from app.core.security.mobile_offline_lease import (
    MobileOfflineLeaseConfigurationError,
    create_mobile_offline_authorization_lease,
    validate_mobile_offline_lease_signing_configuration,
)

_PRIVATE_KEY_B64 = "MC4CAQAwBQYDK2VwBCIEIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g"
_PUBLIC_KEY_B64 = "ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def _settings(*, public_keys: dict[str, str] | None = None) -> MobileSettings:
    return MobileSettings(
        offline_lease_active_kid="lease-2026-01",
        offline_lease_private_key_b64=_PRIVATE_KEY_B64,
        offline_lease_public_keys_json=json.dumps(
            public_keys or {"lease-2026-01": _PUBLIC_KEY_B64}
        ),
        offline_lease_issuer="passdetection-mobile-offline",
        offline_lease_audience="gc-mobile-offline",
        offline_lease_ttl_minutes=720,
        _env_file=None,
    )


def test_ed25519_lease_is_strictly_bound_and_excludes_profile_pii_and_tokens() -> None:
    issued_at = datetime(2026, 8, 19, 10, 30, tzinfo=UTC)
    principal_id = uuid.uuid4()
    account_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    session_id = uuid.uuid4()
    installation_id = "11111111-1111-4111-8111-111111111111"

    compact = create_mobile_offline_authorization_lease(
        principal_id=principal_id,
        account_id=account_id,
        principal_type="passenger",
        agency_id=agency_id,
        passenger_id=passenger_id,
        session_id=session_id,
        session_generation=4,
        installation_id=installation_id,
        principal_generation=7,
        access_generation=9,
        now=issued_at,
        settings=_settings(),
    )

    encoded_header, encoded_payload, encoded_signature = compact.split(".")
    header = json.loads(_decode(encoded_header))
    payload = json.loads(_decode(encoded_payload))
    Ed25519PublicKey.from_public_bytes(_decode(_PUBLIC_KEY_B64)).verify(
        _decode(encoded_signature),
        f"{encoded_header}.{encoded_payload}".encode("ascii"),
    )

    assert header == {
        "alg": "EdDSA",
        "kid": "lease-2026-01",
        "typ": "GC-OFFLINE-AUTH",
        "v": 1,
    }
    assert payload["sub"] == str(principal_id)
    assert payload["account_id"] == str(account_id)
    assert payload["agency_id"] == str(agency_id)
    assert payload["passenger_id"] == str(passenger_id)
    assert payload["session_id"] == str(session_id)
    assert payload["session_generation"] == 4
    assert payload["installation_id"] == installation_id
    assert payload["principal_generation"] == 7
    assert payload["access_generation"] == 9
    assert payload["server_time"] == int(issued_at.timestamp())
    assert payload["iat"] == payload["nbf"] == payload["server_time"]
    assert payload["exp"] - payload["iat"] == 12 * 60 * 60
    assert {"display_name", "email", "phone_number", "access_token", "refresh_token"}.isdisjoint(
        payload
    )


def test_signing_configuration_accepts_bounded_rotation_set_and_rejects_mismatch() -> None:
    second = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
    second_public = second.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    second_encoded = base64.urlsafe_b64encode(second_public).rstrip(b"=").decode("ascii")
    public_keys = json.dumps(
        {
            "lease-2025-12": second_encoded,
            "lease-2026-01": _PUBLIC_KEY_B64,
        }
    )

    validate_mobile_offline_lease_signing_configuration(
        active_kid="lease-2026-01",
        private_key_b64=_PRIVATE_KEY_B64,
        public_keys_json=public_keys,
    )

    with pytest.raises(
        MobileOfflineLeaseConfigurationError,
        match="does not match",
    ):
        validate_mobile_offline_lease_signing_configuration(
            active_kid="lease-2025-12",
            private_key_b64=_PRIVATE_KEY_B64,
            public_keys_json=public_keys,
        )


def test_signing_configuration_rejects_unknown_active_kid_and_unbounded_key_set() -> None:
    with pytest.raises(
        MobileOfflineLeaseConfigurationError,
        match="not present",
    ):
        validate_mobile_offline_lease_signing_configuration(
            active_kid="unknown",
            private_key_b64=_PRIVATE_KEY_B64,
            public_keys_json=json.dumps({"lease-2026-01": _PUBLIC_KEY_B64}),
        )

    with pytest.raises(
        MobileOfflineLeaseConfigurationError,
        match="between 1 and 5",
    ):
        validate_mobile_offline_lease_signing_configuration(
            active_kid="lease-0",
            private_key_b64=_PRIVATE_KEY_B64,
            public_keys_json=json.dumps({f"lease-{index}": _PUBLIC_KEY_B64 for index in range(6)}),
        )
