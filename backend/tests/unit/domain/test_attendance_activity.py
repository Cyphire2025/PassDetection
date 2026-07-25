from app.domain.value_objects.attendance_activity import (
    normalize_attendance_activity_name,
)


def test_attendance_activity_name_normalizes_case_and_whitespace() -> None:
    assert (
        normalize_attendance_activity_name("  After   Lunch\tCount  ")
        == "after lunch count"
    )
