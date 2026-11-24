from __future__ import annotations

import pytest

from app.domain.value_objects.passport_fields import normalize_extracted_passport_dates


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (
            {
                "date_of_birth": "2000-01-01",
                "date_of_issue": "1999-01-01",
                "date_of_expiry": "1998-01-01",
            },
            {"date_of_birth": "2000-01-01"},
        ),
        (
            {
                "date_of_birth": "2000-01-01",
                "date_of_issue": "2001-01-01",
                "date_of_expiry": "1999-01-01",
            },
            {"date_of_birth": "2000-01-01"},
        ),
        (
            {
                "date_of_birth": "2000-01-01",
                "date_of_issue": "2000-01-01",
                "date_of_expiry": "2000-01-01",
            },
            {"date_of_birth": "2000-01-01"},
        ),
        (
            {
                "date_of_birth": "2000-01-01",
                "date_of_issue": "2020-01-01",
                "date_of_expiry": "2030-01-01",
            },
            {
                "date_of_birth": "2000-01-01",
                "date_of_issue": "2020-01-01",
                "date_of_expiry": "2030-01-01",
            },
        ),
        (
            {
                "date_of_birth": "2000-01-01",
                "date_of_issue": "1999-01-01",
                "date_of_expiry": "2030-01-01",
            },
            {"date_of_birth": "2000-01-01", "date_of_expiry": "2030-01-01"},
        ),
        (
            {"date_of_birth": "2000-01-01", "date_of_expiry": "1999-01-01"},
            {"date_of_birth": "2000-01-01"},
        ),
        (
            {
                "date_of_birth": "not-a-date",
                "date_of_issue": "2020-01-01",
                "date_of_expiry": "2030-01-01",
            },
            {"date_of_issue": "2020-01-01", "date_of_expiry": "2030-01-01"},
        ),
    ],
)
def test_extracted_dates_are_consistent_after_every_removed_conflict(
    fields: dict[str, str],
    expected: dict[str, str],
) -> None:
    source = {**fields, "passport_number": "SYNTHETIC123"}
    original = source.copy()

    assert normalize_extracted_passport_dates(source) == {
        **expected,
        "passport_number": "SYNTHETIC123",
    }
    assert source == original
