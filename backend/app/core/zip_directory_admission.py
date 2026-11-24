"""Count real ZIP directory headers before ZipInfo allocation.

The pinned CPython 3.11 footer reader retains ZIP64, comments and prepended data.
Callers supply their own quota and own the stream cursor and content policies.
"""

from __future__ import annotations

import struct
import zipfile
from collections.abc import Callable, Sequence
from typing import IO, cast

_CENTRAL_HEADER = struct.Struct("<4s4B4HL2L5H2L")
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_END_DIRECTORY_SIZE = 5
_END_DIRECTORY_LOCATION = 9
_VARIABLE_LENGTH_FIELDS = slice(12, 15)
_EndRecordReader = Callable[[IO[bytes]], Sequence[object] | None]


class ZipDirectoryMemberLimitError(ValueError):
    """The actual central directory exceeds the caller's member quota."""


def check_zip_directory(stream: IO[bytes], *, max_members: int) -> None:
    # This is the sole interpreter-private seam, pinned by tooling/toolchain.json.
    # Reusing it avoids duplicating ZIP64/comment/self-extracting footer parsing.
    reader = getattr(zipfile, "_EndRecData", None)
    if not callable(reader):
        raise zipfile.BadZipFile("Unsupported ZIP end-record reader")
    record = cast(_EndRecordReader, reader)(stream)
    if record is None or len(record) <= _END_DIRECTORY_LOCATION:
        raise zipfile.BadZipFile("Missing ZIP end record")
    directory_size = record[_END_DIRECTORY_SIZE]
    end_offset = record[_END_DIRECTORY_LOCATION]
    if type(directory_size) is not int or type(end_offset) is not int:
        raise zipfile.BadZipFile("Invalid ZIP directory metadata")
    # This is the standard reader's start_dir formula after its concatenation
    # adjustment: offset + (location - size - offset) == location - size.
    start = end_offset - directory_size
    if directory_size < 0 or start < 0:
        raise zipfile.BadZipFile("Bad offset for central directory")
    stream.seek(start)
    remaining = directory_size
    members = 0
    while remaining:
        if members >= max_members:
            raise ZipDirectoryMemberLimitError(f"ZIP contains more than {max_members} entries")
        raw = stream.read(_CENTRAL_HEADER.size)
        if len(raw) != _CENTRAL_HEADER.size:
            raise zipfile.BadZipFile("Truncated central directory")
        header = _CENTRAL_HEADER.unpack(raw)
        if header[0] != _CENTRAL_SIGNATURE:
            raise zipfile.BadZipFile("Bad magic number for central directory")
        filename_size, extra_size, comment_size = cast(
            tuple[int, int, int], header[_VARIABLE_LENGTH_FIELDS]
        )
        variable_size = filename_size + extra_size + comment_size
        record_size = _CENTRAL_HEADER.size + variable_size
        if record_size > remaining:
            raise zipfile.BadZipFile("Truncated central directory fields")
        stream.seek(variable_size, 1)
        remaining -= record_size
        members += 1
