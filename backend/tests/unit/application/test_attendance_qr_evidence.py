from datetime import UTC, datetime, timedelta

import pytest

from app.application.mobile.attendance_qr_evidence import (
    ATTENDANCE_QR_EVIDENCE_TTL,
    attendance_qr_evidence_epoch,
    build_attendance_qr_evidence,
)

NOW = datetime(2030, 1, 2, 12, tzinfo=UTC)
HASH = "a" * 64


def evidence(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "token_hash": HASH,
        "token_version": 3,
        "is_active": True,
        "revoked_at": None,
        "expires_at": NOW + timedelta(days=2),
        "updated_at": NOW - timedelta(seconds=1),
        "observed_at": NOW,
    }
    values.update(overrides)
    return build_attendance_qr_evidence(**values)


def test_active_evidence_contains_only_a_bounded_sha256_lookup() -> None:
    result = evidence(token_hash=HASH.upper())

    assert result.state == "active"
    assert result.token_hash == HASH
    assert result.token_version == 3
    assert result.evidence_valid_until == NOW + ATTENDANCE_QR_EVIDENCE_TTL
    assert "pdatt:" not in repr(result)


def test_token_expiry_shortens_the_evidence_window() -> None:
    expires_at = NOW + timedelta(minutes=15)
    result = evidence(expires_at=expires_at)

    assert result.state == "active"
    assert result.evidence_valid_until == expires_at


@pytest.mark.parametrize(
    ("overrides", "state"),
    [
        ({"token_version": None}, "missing"),
        ({"token_version": 0}, "inactive"),
        ({"is_active": False}, "inactive"),
        ({"revoked_at": NOW}, "revoked"),
        ({"expires_at": NOW}, "expired"),
        ({"token_hash": "forged"}, "inactive"),
        ({"updated_at": NOW + timedelta(seconds=1)}, "inactive"),
        ({"updated_at": datetime(2030, 1, 2, 11, 59)}, "inactive"),
    ],
)
def test_unusable_tokens_never_expose_lookup_material(overrides, state: str) -> None:  # type: ignore[no-untyped-def]
    result = evidence(**overrides)

    assert result.state == state
    assert result.token_hash is None
    assert result.evidence_valid_until == NOW


def test_naive_observation_is_rejected_instead_of_extending_trust() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evidence(observed_at=datetime(2030, 1, 2, 12))


def test_evidence_epoch_advances_at_the_lease_boundary() -> None:
    assert attendance_qr_evidence_epoch(NOW + ATTENDANCE_QR_EVIDENCE_TTL) == (
        attendance_qr_evidence_epoch(NOW) + 1
    )
