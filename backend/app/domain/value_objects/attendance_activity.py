"""Canonical attendance activity names shared by every group coordinator."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_attendance_activity_name(name: str) -> str:
    """Return the stable identity used to merge concurrently-created activities."""

    return _WHITESPACE.sub(" ", name.strip()).lower()
