from __future__ import annotations

import io
import uuid

from openpyxl import load_workbook

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.export.passport_excel_exporter import (
    PassportExcelExporter,
    _safe_xlsx_value,
)

_OPTION_FLAGS = {
    "nearest_international_airport_enabled": False,
    "ask_nearest_domestic_airport": False,
    "base_city_enabled": False,
    "staff_code_enabled": False,
    "meal_preference_enabled": False,
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
    }.isdisjoint(headers)
    assert values["Surname"] == "VASHISTHA"
    assert values["Given Names"] == "NIPUN KUMAR"
    assert values["Nationality"] == "India"


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
