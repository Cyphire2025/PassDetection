from __future__ import annotations

import io
import uuid

import pytest
from openpyxl import load_workbook

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.export.passport_excel_exporter import (
    PassportExcelExporter,
    _country_display_name,
    _gender_display_value,
    _nationality_display_value,
    _safe_xlsx_value,
)

_OPTION_FLAGS = {
    "nearest_international_airport_enabled": False,
    "ask_nearest_domestic_airport": False,
    "base_city_enabled": False,
    "staff_code_enabled": False,
    "meal_preference_enabled": False,
    "relation_with_qualifier_enabled": False,
}


def _submission(
    group_id: uuid.UUID,
    *,
    client_name: str = "Traveller",
    fields: dict[str, str] | None = None,
) -> PassportSubmission:
    submission = PassportSubmission.create(
        group_id=group_id,
        agency_id=uuid.uuid4(),
        client_name=client_name,
        client_email=None,
        image_s3_key="front.jpg",
    )
    submission.submit_client_review(
        fields or {},
        client_email="traveller@example.com",
        client_phone="9876543210",
        departure_city="Delhi",
        nearest_domestic_airport="Indira Gandhi International Airport",
    )
    return submission


def _worksheet(content: bytes):
    return load_workbook(io.BytesIO(content), data_only=False).active


def _row_values(worksheet) -> tuple[list[str], dict[str, object]]:
    headers = [cell.value for cell in worksheet[4]]
    return headers, {
        header: worksheet.cell(row=5, column=index + 1).value
        for index, header in enumerate(headers)
    }


def test_export_omits_internal_and_disabled_columns_and_formats_identity() -> None:
    group_id = uuid.uuid4()
    submission = _submission(
        group_id,
        fields={
            "surname": "vAsHiStHa",
            "given_names": "niPun kuMar",
            "passport_number": "W1234567",
            "nationality": "IND",
            "issuing_country": "IND",
            "base_city": "Delhi",
            "staff_code": "GC-42",
            "meal_preference": "Veg",
        },
    )

    content = PassportExcelExporter().export_group(
        [submission],
        group_name="Test Group",
        group_details={
            group_id: {
                "name": "Test Group",
                **_OPTION_FLAGS,
            }
        },
    )
    headers, values = _row_values(_worksheet(content))

    assert {
        "Submitted At",
        "Reviewed At",
        "Confidence",
        "Issuing Country",
        "Status",
        "Nearest International Airport",
        "Nearest Domestic Airport",
        "Base City",
        "Staff Code",
        "Meal Preference",
        "Relation with Qualifier",
    }.isdisjoint(headers)
    assert values["Surname"] == "VASHISTHA"
    assert values["Given Names"] == "NIPUN KUMAR"
    assert values["Nationality"] == "Indian"


@pytest.mark.parametrize("source", ("IN", "IND", "India", "indian"))
def test_export_formats_indian_nationality_without_changing_country_labels(
    source: str,
) -> None:
    assert _nationality_display_value(source) == "Indian"
    assert _country_display_name(source if source != "indian" else "India") == "India"


def test_export_includes_only_group_options_enabled_in_the_workbook() -> None:
    first_group_id = uuid.uuid4()
    second_group_id = uuid.uuid4()
    first = _submission(first_group_id)
    second = _submission(
        second_group_id,
        fields={
            "base_city": "Mumbai",
            "staff_code": "GC-77",
            "meal_preference": "Jain",
        },
    )

    content = PassportExcelExporter().export_group(
        [first, second],
        group_name="Selected Groups",
        group_details={
            first_group_id: {
                "name": "First",
                **_OPTION_FLAGS,
            },
            second_group_id: {
                "name": "Second",
                **_OPTION_FLAGS,
                "base_city_enabled": True,
                "staff_code_enabled": True,
                "meal_preference_enabled": True,
            },
        },
    )
    worksheet = _worksheet(content)
    headers = [cell.value for cell in worksheet[4]]
    second_values = {
        header: worksheet.cell(row=6, column=index + 1).value
        for index, header in enumerate(headers)
    }

    assert "Nearest International Airport" not in headers
    assert "Nearest Domestic Airport" not in headers
    assert "Base City" in headers
    assert "Staff Code" in headers
    assert "Meal Preference" in headers
    assert second_values["Base City"] == "Mumbai"
    assert second_values["Staff Code"] == "GC-77"
    assert second_values["Meal Preference"] == "Jain"


def test_export_includes_relation_snapshot_only_for_enabled_groups() -> None:
    group_id = uuid.uuid4()
    submission = _submission(group_id)
    submission.qualifier_enabled_snapshot = True
    submission.qualifier_is_self = False
    submission.qualifier_relation_code = "spouse"
    submission.qualifier_relation_label = "Spouse"

    worksheet = _worksheet(
        PassportExcelExporter().export_group(
            [submission],
            group_name="Qualifier Group",
            group_details={
                group_id: {
                    "name": "Qualifier Group",
                    **_OPTION_FLAGS,
                    "relation_with_qualifier_enabled": True,
                }
            },
        )
    )
    headers, values = _row_values(worksheet)

    assert "Relation with Qualifier" in headers
    assert values["Relation with Qualifier"] == "Spouse"


def test_export_neutralizes_formula_like_text_after_leading_whitespace() -> None:
    group_id = uuid.uuid4()
    submission = _submission(
        group_id,
        client_name="   =HYPERLINK(\"https://example.test\",\"click\")",
        fields={
            "surname": "+cmd",
            "given_names": "-2+3",
            "passport_number": "@SUM(A1:A2)",
        },
    )

    worksheet = _worksheet(
        PassportExcelExporter().export_group(
            [submission],
            group_name="Test Group",
            group_details={group_id: {"name": "Test Group", **_OPTION_FLAGS}},
        )
    )
    headers, values = _row_values(worksheet)

    for header in ("Client Name", "Surname", "Given Names", "Passport Number"):
        cell = worksheet.cell(row=5, column=headers.index(header) + 1)
        assert cell.data_type == "s"
        assert str(values[header]).startswith("'")
    assert _safe_xlsx_value(42) == 42
    assert _safe_xlsx_value("2026-07-17") == "2026-07-17"


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("M", "Male"),
        ("m", "Male"),
        ("Male", "Male"),
        ("male", "Male"),
        (" F ", "Female"),
        ("f", "Female"),
        ("Female", "Female"),
        ("female", "Female"),
    ),
)
def test_export_normalizes_supported_gender_values(
    source: str,
    expected: str,
) -> None:
    group_id = uuid.uuid4()
    submission = _submission(group_id, fields={"sex": source})

    worksheet = _worksheet(
        PassportExcelExporter().export_group(
            [submission],
            group_name="Test Group",
            group_details={group_id: {"name": "Test Group", **_OPTION_FLAGS}},
        )
    )
    _, values = _row_values(worksheet)

    assert values["Sex"] == expected


def test_export_gender_normalization_does_not_invent_unknown_values() -> None:
    assert _gender_display_value("X") == "X"
    assert _gender_display_value(None) is None


def test_export_writes_all_visible_dates_as_native_dd_dot_mm_dot_yyyy() -> None:
    group_id = uuid.uuid4()
    submission = _submission(
        group_id,
        fields={
            "date_of_birth": "1972-08-30",
            "date_of_issue": "2023-08-10",
            "date_of_expiry": "2033-08-09",
        },
    )

    worksheet = _worksheet(
        PassportExcelExporter().export_group(
            [submission],
            group_name="Test Group",
            group_details={
                group_id: {
                    "name": "Test Group",
                    "travel_date": "2026-07-17",
                    "return_date": "2026-07-25",
                    **_OPTION_FLAGS,
                }
            },
        )
    )
    headers = [cell.value for cell in worksheet[4]]
    expected = {
        "Travel/Departure Date": "17.07.2026",
        "Return Date": "25.07.2026",
        "Date of Birth": "30.08.1972",
        "Date of Issue": "10.08.2023",
        "Date of Expiry": "09.08.2033",
    }

    for header, display_value in expected.items():
        cell = worksheet.cell(row=5, column=headers.index(header) + 1)
        assert cell.is_date
        assert cell.number_format == "DD.MM.YYYY"
        assert cell.value.strftime("%d.%m.%Y") == display_value
