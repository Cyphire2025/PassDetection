"""Collection and WhatsApp consumers share one unambiguous representation."""

import pytest

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.domain.value_objects.phone_number import normalize_phone_number, phone_numbers_equal
from app.presentation.api.v1.schemas.passport_schemas import ClientSubmitPassportRequest


@pytest.mark.parametrize(("raw", "expected"), [
    ("9876543210", "+919876543210"),
    ("+91 (98765) 43210", "+919876543210"),
    ("0091 98765 43210", "+919876543210"),
    ("919876543210", "+919876543210"),
    ("+44 20 1234 5678", "+442012345678"),
    ("+12345678", "+12345678"),
    ("+123456789012345", "+123456789012345"),
    (None, None), ("", None), ("   ", None),
    ("1234567", None), ("12345678", None),
    ("+1234567890123456", None), ("1234567890123456", None),
    ("++919876543210", None), ("91+9876543210", None),
    ("+01234567890", None), ("0001234567890", None),
    ("phone:9876543210", None), ("९८७६५४३२१०", None),
])
def test_shared_phone_contract(raw, expected):
    assert normalize_phone_number(raw) == expected
    assert normalize_whatsapp_phone(raw) == expected


def test_replay_comparison_handles_legacy_format_without_equating_invalid_and_absent():
    assert phone_numbers_equal("98765 43210", "+919876543210")
    assert phone_numbers_equal("0091-9876543210", "9876543210")
    assert phone_numbers_equal(None, "")
    assert not phone_numbers_equal("bad number", None)
    assert not phone_numbers_equal("bad number", "bad number")
    assert not phone_numbers_equal("9876543210", "9876543211")


def test_public_schema_normalizes_both_contacts_and_preserves_optional_blank():
    request = ClientSubmitPassportRequest(
        group_token="public-group-token", confirmed_fields={"given_names": "AMAN"},
        client_phone="9876543210", family_head_phone="0091 98765 43211",
    )
    assert request.client_phone == "+919876543210"
    assert request.family_head_phone == "+919876543211"
    blank = ClientSubmitPassportRequest(
        group_token="public-group-token", confirmed_fields={"given_names": "AMAN"},
        client_phone="", family_head_phone="  ",
    )
    assert blank.client_phone is None
    assert blank.family_head_phone is None
