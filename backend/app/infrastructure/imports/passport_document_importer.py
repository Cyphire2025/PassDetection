"""Safe, filename-driven import of staff passport document bundles.

The preview path is deliberately stateless: files are inspected in memory and no
object is written until the caller explicitly accepts the matched distribution.
"""

from __future__ import annotations

import re
import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security.upload_validator import UploadValidator, ValidatedUpload


MAX_ARCHIVES = 8
MAX_DIRECT_FILES = 3_000
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 5_000
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 3 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
_NAME = re.compile(r"^STF_(?P<staff_code>[A-Za-z0-9-]{1,80})_(?P<document_type>PHOTO|FRONT|BACK)\.(?P<extension>jpe?g|png|webp)$", re.IGNORECASE)


@dataclass(frozen=True)
class PassportDocumentFile:
    filename: str
    staff_code: str
    document_type: str
    upload: ValidatedUpload


@dataclass(frozen=True)
class RejectedPassportDocument:
    filename: str
    reason: str


class PassportDocumentImporter:
    """Expands safe ZIPs and validates `STF_<staffcode>_<kind>` images."""

    def __init__(self, validator: UploadValidator | None = None) -> None:
        self._validator = validator or UploadValidator()

    def collect(
        self,
        files: list[tuple[str, bytes, str | None]],
        *,
        allowed_staff_codes: set[str] | None = None,
    ) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
        accepted: list[PassportDocumentFile] = []
        rejected: list[RejectedPassportDocument] = []
        archive_count = sum(1 for _, content, _ in files if zipfile.is_zipfile(BytesIO(content)))
        direct_count = len(files) - archive_count
        if archive_count > MAX_ARCHIVES or direct_count > MAX_DIRECT_FILES:
            return accepted, [RejectedPassportDocument("upload", f"Upload at most {MAX_ARCHIVES} ZIP archives or {MAX_DIRECT_FILES} direct image files at a time")]

        for filename, content, declared_type in files:
            if len(content) > MAX_ARCHIVE_BYTES:
                rejected.append(RejectedPassportDocument(filename, "File exceeds the 512 MB import limit"))
                continue
            if zipfile.is_zipfile(BytesIO(content)):
                accepted_part, rejected_part = self._collect_zip(filename, content, allowed_staff_codes=allowed_staff_codes)
            else:
                accepted_part, rejected_part = self._collect_one(filename, content, declared_type, allowed_staff_codes=allowed_staff_codes)
            accepted.extend(accepted_part)
            rejected.extend(rejected_part)

        # A document type may be supplied only once for each passenger. This
        # avoids a silent last-write-wins replacement during final persistence.
        seen: set[tuple[str, str]] = set()
        unique: list[PassportDocumentFile] = []
        for item in accepted:
            key = (item.staff_code.casefold(), item.document_type)
            if key in seen:
                rejected.append(RejectedPassportDocument(item.filename, "Duplicate document type for this staff code"))
            else:
                seen.add(key)
                unique.append(item)
        return unique, rejected

    def _collect_zip(
        self,
        archive_name: str,
        content: bytes,
        *,
        allowed_staff_codes: set[str] | None,
    ) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
        accepted: list[PassportDocumentFile] = []
        rejected: list[RejectedPassportDocument] = []
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > MAX_MEMBERS:
                    return accepted, [RejectedPassportDocument(archive_name, f"ZIP contains more than {MAX_MEMBERS} entries")]
                if any(info.flag_bits & 0x1 for info in members):
                    return accepted, [RejectedPassportDocument(archive_name, "Encrypted ZIP archives are not allowed")]
                total_uncompressed = 0
                for info in members:
                    path = PurePosixPath(info.filename.replace("\\", "/"))
                    if not info.filename or path.is_absolute() or ".." in path.parts:
                        rejected.append(RejectedPassportDocument(info.filename or archive_name, "Unsafe ZIP path"))
                        continue
                    if info.is_dir():
                        continue
                    # Unix symlinks are never valid passport images.
                    if stat.S_ISLNK(info.external_attr >> 16):
                        rejected.append(RejectedPassportDocument(info.filename, "ZIP symlink entries are not allowed"))
                        continue
                    if info.file_size > MAX_MEMBER_BYTES:
                        rejected.append(RejectedPassportDocument(info.filename, "Image exceeds the 20 MB per-file limit"))
                        continue
                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                        return accepted, rejected + [RejectedPassportDocument(archive_name, "ZIP exceeds the 3 GB extracted-size limit")]
                    if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                        rejected.append(RejectedPassportDocument(info.filename, "Suspicious ZIP compression ratio"))
                        continue
                    basename = path.name
                    quick_match = self._parse_name(basename)
                    if quick_match is None:
                        rejected.append(RejectedPassportDocument(info.filename, "Expected filename STF_<staffcode>_PHOTO, _FRONT, or _BACK with a JPEG, PNG, or WebP extension"))
                        continue
                    if allowed_staff_codes is not None and quick_match[0] not in allowed_staff_codes:
                        rejected.append(RejectedPassportDocument(info.filename, "Staff code was not found in this group"))
                        continue
                    member_content = archive.read(info)
                    part_accepted, part_rejected = self._collect_one(basename, member_content, None, allowed_staff_codes=allowed_staff_codes)
                    accepted.extend(part_accepted)
                    rejected.extend(part_rejected)
        except (OSError, zipfile.BadZipFile, RuntimeError):
            rejected.append(RejectedPassportDocument(archive_name, "Unreadable or encrypted ZIP archive"))
        return accepted, rejected

    def _collect_one(
        self,
        filename: str,
        content: bytes,
        declared_type: str | None,
        *,
        allowed_staff_codes: set[str] | None,
    ) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
        basename = PurePosixPath(filename.replace("\\", "/")).name
        parsed = self._parse_name(basename)
        if parsed is None:
            return [], [RejectedPassportDocument(filename, "Expected filename STF_<staffcode>_PHOTO, _FRONT, or _BACK with a JPEG, PNG, or WebP extension")]
        staff_code, document_type = parsed
        if allowed_staff_codes is not None and staff_code not in allowed_staff_codes:
            return [], [RejectedPassportDocument(filename, "Staff code was not found in this group")]
        try:
            upload = self._validator.validate(content=content, filename=basename, declared_content_type=declared_type)
        except ImageValidationError as exc:
            return [], [RejectedPassportDocument(filename, exc.message)]
        return [PassportDocumentFile(
            filename=basename,
            staff_code=staff_code,
            document_type=document_type,
            upload=upload,
        )], []

    def _parse_name(self, filename: str) -> tuple[str, str] | None:
        match = _NAME.fullmatch(filename)
        if not match:
            return None
        return match.group("staff_code").upper(), match.group("document_type").lower()
