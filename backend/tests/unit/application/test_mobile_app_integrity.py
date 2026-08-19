from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.application.mobile.app_integrity import (
    MobileIntegrityChallenge,
    MobileIntegrityRejected,
    app_attest_key_registration_request_hash,
    create_mobile_integrity_challenge,
    mobile_document_authorization_request_hash,
    validate_mobile_integrity_challenge,
)
from app.infrastructure.security.mobile_integrity_challenges import (
    InMemoryMobileIntegrityChallengeStore,
)


def _digest(value: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode()


def _challenge_fixture() -> tuple[MobileIntegrityChallenge, dict[str, object]]:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    values: dict[str, object] = {
        "provider": "app_attest",
        "action": "document_download_authorize",
        "request_hash": _digest(b"request"),
        "agency_id": uuid.uuid4(),
        "account_id": uuid.uuid4(),
        "session_id": uuid.uuid4(),
        "device_identifier_hash": "a" * 64,
        "key_id": "K" * 48,
        "binding_secret": b"server-binding-secret-with-sufficient-entropy",
        "now": now,
    }
    challenge = create_mobile_integrity_challenge(
        **values,
        ttl_seconds=120,
    )
    return challenge, values


def test_request_hash_contracts_are_canonical_and_resource_bound() -> None:
    group_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    document_id = uuid.UUID("22222222-2222-4222-8222-222222222222")
    expected = _digest(
        (
            "gc-mobile-integrity-v1\0document_download_authorize\0"
            f"{group_id}\0{document_id}\0{7}"
        ).encode("ascii")
    )

    assert mobile_document_authorization_request_hash(
        group_id=group_id,
        document_id=document_id,
        version=7,
    ) == expected
    assert mobile_document_authorization_request_hash(
        group_id=group_id,
        document_id=document_id,
        version=8,
    ) != expected
    key_id = "A" * 48
    assert app_attest_key_registration_request_hash(key_id=key_id) == _digest(
        f"gc-mobile-integrity-v1\0app_attest_key_register\0{key_id}".encode("ascii")
    )


def test_challenge_record_is_bounded_round_trippable_and_contains_no_raw_identity() -> None:
    challenge, values = _challenge_fixture()

    encoded = challenge.to_json()

    assert len(encoded) < 4_096
    assert MobileIntegrityChallenge.from_json(encoded) == challenge
    for raw_value in (
        values["agency_id"],
        values["account_id"],
        values["session_id"],
        values["device_identifier_hash"],
        values["key_id"],
    ):
        assert str(raw_value) not in encoded
    payload = json.loads(encoded)
    assert set(payload) == {
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
    }


@pytest.mark.parametrize(
    ("field", "replacement", "expected_reason"),
    [
        ("provider", "play_integrity", "binding_provider"),
        ("action", "app_attest_key_register", "binding_action"),
        ("request_hash", _digest(b"wrong-request"), "binding_request_hash"),
        ("agency_id", uuid.uuid4(), "binding_agency"),
        ("account_id", uuid.uuid4(), "binding_account"),
        ("session_id", uuid.uuid4(), "binding_session"),
        ("device_identifier_hash", "b" * 64, "binding_installation"),
        ("key_id", "Z" * 48, "binding_key"),
    ],
)
def test_challenge_rejects_cross_context_substitution(
    field: str,
    replacement: object,
    expected_reason: str,
) -> None:
    challenge, values = _challenge_fixture()
    values[field] = replacement
    values["now"] = values["now"] + timedelta(seconds=119)  # type: ignore[operator]

    with pytest.raises(MobileIntegrityRejected, match=expected_reason) as caught:
        validate_mobile_integrity_challenge(challenge, **values)

    assert caught.value.reason == expected_reason


def test_challenge_expiry_is_fail_closed_at_the_boundary() -> None:
    challenge, values = _challenge_fixture()
    values["now"] = values["now"] + timedelta(seconds=120)  # type: ignore[operator]

    with pytest.raises(MobileIntegrityRejected) as caught:
        validate_mobile_integrity_challenge(challenge, **values)

    assert caught.value.reason == "challenge_expired"


@pytest.mark.asyncio
async def test_in_memory_challenge_is_one_time_and_expiry_bounded() -> None:
    challenge, _values = _challenge_fixture()

    def clock() -> float:
        return float(challenge.expires_at_epoch - 1)

    store = InMemoryMobileIntegrityChallengeStore(clock=clock)
    await store.put(challenge)

    assert await store.consume(challenge.challenge_id) == challenge
    assert await store.consume(challenge.challenge_id) is None

    expired_store = InMemoryMobileIntegrityChallengeStore(
        clock=lambda: challenge.expires_at_epoch
    )
    await expired_store.put(challenge)
    assert await expired_store.consume(challenge.challenge_id) is None


def test_challenge_decoder_rejects_non_base64url_digest_even_at_correct_length() -> None:
    challenge, _values = _challenge_fixture()
    payload = json.loads(challenge.to_json())
    payload["request_hash"] = "!" * 43

    with pytest.raises(ValueError, match="digest"):
        MobileIntegrityChallenge.from_json(json.dumps(payload))
