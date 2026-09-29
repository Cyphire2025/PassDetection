"""Pure shared spreadsheet value conversion and bounded ZIP structure validation."""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any
from zipfile import ZipFile


def excel_cell_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value).strip()


def validate_excel_archive(
    payload: bytes,
    *,
    max_members: int = 2000,
    max_uncompressed_bytes: int = 50 * 1024 * 1024,
    max_compression_ratio: int = 250,
    ratio_threshold_bytes: int = 64 * 1024,
) -> None:
    with ZipFile(BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise ValueError("The Excel contact file contains too many archive entries")
        if sum(member.file_size for member in members) > max_uncompressed_bytes:
            raise ValueError("The Excel contact file expands beyond the allowed size")
        for member in members:
            if (
                member.file_size > ratio_threshold_bytes
                and member.compress_size > 0
                and member.file_size / member.compress_size > max_compression_ratio
            ):
                raise ValueError("The Excel contact file has an unsafe compression ratio")
