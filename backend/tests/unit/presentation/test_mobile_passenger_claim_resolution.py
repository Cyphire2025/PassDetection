from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.security.mobile_jwt import hash_mobile_secondary_factor
from app.presentation.api.v1.routes.mobile_auth import _matching_passenger_claims


def _row(*, factor: str | None, requires_secondary: bool = False):
    identity_id = uuid.uuid4()
    identity = SimpleNamespace(
        id=identity_id,
        requires_secondary_verification=requires_secondary,
        secondary_factor_hash=(
            hash_mobile_secondary_factor(identity_id, factor)
            if factor is not None
            else None
        ),
    )
    return identity, SimpleNamespace(), SimpleNamespace()


def test_cross_group_phone_matches_require_factor_before_claim_selection() -> None:
    first = _row(factor="EMP-101")
    second = _row(factor="EMP-202")

    assert (
        _matching_passenger_claims(
            [first, second], claim_id=None, verification_value=None
        )
        == []
    )
    assert _matching_passenger_claims(
        [first, second], claim_id=None, verification_value="EMP-101"
    ) == [first]


def test_same_strong_factor_can_reveal_only_linked_trip_choices() -> None:
    first = _row(factor="BOOKING-77")
    second = _row(factor="BOOKING-77")
    unrelated = _row(factor="BOOKING-88")

    assert _matching_passenger_claims(
        [first, second, unrelated],
        claim_id=None,
        verification_value="BOOKING-77",
    ) == [first, second]
    assert _matching_passenger_claims(
        [first, second, unrelated],
        claim_id=second[0].id,
        verification_value="BOOKING-77",
    ) == [second]


def test_mixed_multi_match_never_accepts_factorless_identity_by_identifier() -> None:
    factorless = _row(factor=None)
    shared = _row(factor="EMP-303", requires_secondary=True)

    assert (
        _matching_passenger_claims(
            [factorless, shared],
            claim_id=factorless[0].id,
            verification_value=None,
        )
        == []
    )
    assert _matching_passenger_claims(
        [factorless, shared],
        claim_id=shared[0].id,
        verification_value="EMP-303",
    ) == [shared]


def test_single_unambiguous_phone_identity_needs_only_verified_otp() -> None:
    identity = _row(factor=None)

    assert _matching_passenger_claims(
        [identity], claim_id=None, verification_value=None
    ) == [identity]
