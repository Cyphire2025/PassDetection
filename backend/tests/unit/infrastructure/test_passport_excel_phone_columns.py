from __future__ import annotations

import pytest

from app.infrastructure.export.passport_excel_phone_columns import (
    VERIFIED_WHATSAPP_HEADER,
    is_phone_export_field,
)


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("whatsapp:upload_phone", "Upload Phone"),
        ("whatsapp:whatsapp_phone", "WhatsApp Phone"),
        ("", VERIFIED_WHATSAPP_HEADER),
        ("custom_detail:id", f"{VERIFIED_WHATSAPP_HEADER} (Custom Detail)"),
        ("custom:id", "Phone Number (Custom Question 2)"),
        ("whatsapp:misc", "Old Phone No"),
        ("whatsapp:mobile_no", "Mobile No."),
        ("whatsapp:telephone", "Telephone"),
        ("clientPhone", "Contact"),
        ("custom_detail:id", "Family Head Phone"),
        ("custom_detail:id", "Emergency contact number"),
        ("whatsapp:phone_number", "Phone Number 2"),
        ("whatsapp:verifiedwhatsappnumbers", "Stored value"),
        ("", "  WHATSAPP / NUMBER  "),
    ],
)
def test_phone_export_field_recognizes_number_columns(key: str, label: str) -> None:
    assert is_phone_export_field(key, label)


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("whatsapp:department", "Department"),
        ("whatsapp:smartphone_model", "Smartphone Model"),
        ("whatsapp:contact_preference", "Contact Preference"),
        ("custom_detail:id", "Emergency Contact Name"),
        ("whatsapp:whatsapp_email", "WhatsApp Email"),
        ("whatsapp:phone_model", "Phone Model"),
        ("whatsapp:whatsapp_status", "WhatsApp Status"),
        ("", ""),
    ],
)
def test_phone_export_field_preserves_other_metadata(key: str, label: str) -> None:
    assert not is_phone_export_field(key, label)
