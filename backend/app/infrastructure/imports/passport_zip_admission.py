"""Bound ZIP directory records before the standard reader allocates ZipInfo objects.

The reviewed CPython 3.11 end-record reader handles ZIP64 and prepended data.
Count actual fixed-size central headers; the untrusted advertised entry count
does not constrain the standard reader. Image decoding remains in UploadValidator.
"""

from __future__ import annotations

from typing import IO

from app.core.zip_directory_admission import (
    _CENTRAL_HEADER as _CENTRAL_HEADER,
)
from app.core.zip_directory_admission import (
    _CENTRAL_SIGNATURE as _CENTRAL_SIGNATURE,
)
from app.core.zip_directory_admission import (
    _END_DIRECTORY_LOCATION as _END_DIRECTORY_LOCATION,
)
from app.core.zip_directory_admission import (
    _END_DIRECTORY_SIZE as _END_DIRECTORY_SIZE,
)
from app.core.zip_directory_admission import (
    _VARIABLE_LENGTH_FIELDS as _VARIABLE_LENGTH_FIELDS,
)
from app.core.zip_directory_admission import (
    ZipDirectoryMemberLimitError,
    check_zip_directory,
)
from app.core.zip_directory_admission import (
    _EndRecordReader as _EndRecordReader,
)


class PassportZipMemberLimitError(ValueError):
    """The directory exceeds the existing import member limit."""


def admit_passport_zip_directory(stream: IO[bytes], *, max_members: int) -> None:
    """Preserve the cursor and count directory records with constant working memory."""
    position = stream.tell()
    try:
        _check_directory(stream, max_members=max_members)
    finally:
        stream.seek(position)


def _check_directory(stream: IO[bytes], *, max_members: int) -> None:
    try:
        check_zip_directory(stream, max_members=max_members)
    except ZipDirectoryMemberLimitError as exc:
        raise PassportZipMemberLimitError(str(exc)) from exc
