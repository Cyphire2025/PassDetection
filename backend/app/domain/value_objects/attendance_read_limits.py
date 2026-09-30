"""Opt-in limits for retained attendance projections; website defaults are unchanged."""

from dataclasses import dataclass


class AttendanceReadLimitError(ValueError):
    def __init__(self) -> None:
        super().__init__("attendance_read_limit")


@dataclass(frozen=True, slots=True)
class AttendanceReadLimits:
    activities: int = 100
    source_rows: int = 5000
    derived_combinations: int = 10000

    def require_work(self, activity_count: int, source_count: int) -> None:
        if activity_count * source_count > self.derived_combinations:
            raise AttendanceReadLimitError()
