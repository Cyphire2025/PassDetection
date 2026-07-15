from __future__ import annotations

from app.presentation.api.v1.routes.rooming import _passenger_matches_room_allocation


def test_gender_room_rejects_opposite_passenger_tag() -> None:
    assert _passenger_matches_room_allocation("male", [], "female") is False
    assert _passenger_matches_room_allocation("female", [], "male") is False


def test_gender_room_accepts_matching_passenger_tag() -> None:
    assert _passenger_matches_room_allocation("male", [], "male") is True
    assert _passenger_matches_room_allocation("female", [], "female") is True


def test_mixed_room_accepts_any_passenger_tag() -> None:
    assert _passenger_matches_room_allocation("male", [], "mixed") is True
    assert _passenger_matches_room_allocation("female", [], "mixed") is True
    assert _passenger_matches_room_allocation("unspecified", [], "mixed") is True


def test_vip_room_requires_vip_special_request() -> None:
    assert _passenger_matches_room_allocation("unspecified", ["vip"], "vip") is True
    assert _passenger_matches_room_allocation("unspecified", [], "vip") is False
