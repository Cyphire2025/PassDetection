"""Secure ZIP packaging for original passport submission images."""

from __future__ import annotations

import re
import tempfile
import unicodedata
import zipfile
from pathlib import PurePosixPath
from typing import BinaryIO

from app.domain.entities.entities import PassportSubmission
from app.domain.repositories.interfaces import IObjectStorageRepository


_UNSAFE_COMPONENT = re.compile(r"[\\/:*?\"<>|\x00-\x1f\x7f]+")
_SAFE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class PassportImageExportError(ValueError):
    """Base error for a ZIP export that cannot be produced safely."""


class MissingPassportImagesError(PassportImageExportError):
    """Raised when a submitted passenger is missing compulsory originals."""


class PassportImageExportLimitError(PassportImageExportError):
    """Raised when an export exceeds its bounded resource limits."""


class PassportImageZipExporter:
    """Build a collision-safe ZIP in a memory-to-disk spooled file."""

    MAX_SUBMISSIONS = 5_000
    MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
    SPOOL_MEMORY_BYTES = 8 * 1024 * 1024

    async def export_group(
        self,
        submissions: list[PassportSubmission],
        *,
        group_name: str,
        staff_code_enabled: bool,
        storage: IObjectStorageRepository,
    ) -> tuple[BinaryIO, int, int]:
        if len(submissions) > self.MAX_SUBMISSIONS:
            raise PassportImageExportLimitError(
                f"Image export is limited to {self.MAX_SUBMISSIONS} passengers at a time."
            )

        ordered = sorted(
            submissions,
            key=lambda item: (
                self._passenger_folder_base(item, staff_code_enabled=staff_code_enabled).casefold(),
                str(item.id),
            ),
        )
        missing = [
            item.client_name
            for item in ordered
            if not item.image_s3_key
            or item.image_s3_key.startswith("excel-imports/")
            or not item.passport_back_s3_key
        ]
        if missing:
            preview = ", ".join(missing[:5])
            remainder = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
            raise MissingPassportImagesError(
                f"Passport front and back images are required before export for: {preview}{remainder}."
            )

        spool = tempfile.SpooledTemporaryFile(max_size=self.SPOOL_MEMORY_BYTES, mode="w+b")
        total_bytes = 0
        entry_count = 0
        root = f"{sanitize_zip_component(group_name, fallback='GROUP')}_PASSPORT_IMAGES"
        used_folders: set[str] = set()

        try:
            with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                archive.writestr(self._zip_info(f"{root}/", is_directory=True), b"")
                for submission in ordered:
                    base_folder = self._passenger_folder_base(
                        submission,
                        staff_code_enabled=staff_code_enabled,
                    )
                    passenger_folder = base_folder
                    occurrence = 1
                    while passenger_folder.casefold() in used_folders:
                        occurrence += 1
                        passenger_folder = f"{base_folder}_{occurrence}"
                    used_folders.add(passenger_folder.casefold())

                    originals = [
                        ("passportfront", submission.image_s3_key),
                        ("passportback", submission.passport_back_s3_key),
                    ]
                    if submission.passport_photo_s3_key:
                        originals.insert(0, ("visaimage", submission.passport_photo_s3_key))

                    for label, storage_key in originals:
                        if not storage_key:
                            continue
                        content = await storage.get_file(storage_key)
                        total_bytes += len(content)
                        if total_bytes > self.MAX_UNCOMPRESSED_BYTES:
                            raise PassportImageExportLimitError(
                                "Image export exceeds the 2 GB uncompressed safety limit."
                            )
                        extension = safe_storage_extension(storage_key)
                        archive_path = f"{root}/{passenger_folder}/{passenger_folder}_{label}{extension}"
                        archive.writestr(self._zip_info(archive_path), content)
                        entry_count += 1

            spool.seek(0)
            return spool, entry_count, total_bytes
        except Exception:
            spool.close()
            raise

    @staticmethod
    def _passenger_folder_base(submission: PassportSubmission, *, staff_code_enabled: bool) -> str:
        client_name = sanitize_zip_component(submission.client_name, fallback="CLIENT")
        if not staff_code_enabled:
            return client_name
        metadata = submission.staff_metadata or {}
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        raw_staff_code = metadata.get("staff_code") or fields.get("staff_code")
        staff_code = sanitize_zip_component(str(raw_staff_code), fallback="") if raw_staff_code else ""
        return f"{staff_code}_{client_name}" if staff_code else client_name

    @staticmethod
    def _zip_info(path: str, *, is_directory: bool = False) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 3
        info.external_attr = (0o755 if is_directory else 0o644) << 16
        if is_directory:
            info.external_attr |= 0x10
        return info


def sanitize_zip_component(value: str, *, fallback: str) -> str:
    """Return one safe ZIP path component; separators and dot segments cannot survive."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = _UNSAFE_COMPONENT.sub("_", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ._")
    normalized = normalized[:100].rstrip(" .")
    if not normalized:
        return fallback
    if normalized.upper() in _WINDOWS_RESERVED:
        normalized = f"_{normalized}"
    if normalized in {".", ".."}:
        return fallback
    return normalized


def safe_storage_extension(storage_key: str) -> str:
    suffix = PurePosixPath(storage_key).suffix.lower()
    return suffix if suffix in _SAFE_IMAGE_EXTENSIONS else ".bin"


def safe_download_filename(group_name: str) -> str:
    component = sanitize_zip_component(group_name, fallback="GROUP")
    ascii_component = unicodedata.normalize("NFKD", component).encode("ascii", "ignore").decode("ascii")
    ascii_component = re.sub(r"[^A-Za-z0-9._ -]+", "_", ascii_component).strip(" ._") or "GROUP"
    return f"{ascii_component[:100]}_PASSPORT_IMAGES.zip"
