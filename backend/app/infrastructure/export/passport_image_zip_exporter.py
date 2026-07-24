"""Secure ZIP packaging for effective passport submission image views."""

from __future__ import annotations

import asyncio
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO, Iterable, Mapping

from app.domain.entities.entities import PassportSubmission
from app.domain.exceptions.exceptions import StorageError
from app.domain.repositories.interfaces import IObjectStorageRepository
from app.domain.value_objects.passport_image_crop import PassportImageCrop, PassportImageType
from app.domain.value_objects.personnel_codes import (
    prefixed_agent_employee_code,
    prefixed_staff_code,
)
from app.infrastructure.imaging.passport_image_cropper import render_saved_passport_image_crop

_UNSAFE_COMPONENT = re.compile(r"[\\/:*?\"<>|\x00-\x1f\x7f]+")
_SAFE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_UNASSIGNED_ZONE_FOLDER = "UNASSIGNED_ZONE"
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class _ArchiveImageSpec:
    path_stem: str
    storage_key: str
    crop: PassportImageCrop | None


@dataclass(frozen=True, slots=True)
class _LoadedArchiveImage:
    path: str
    content: bytes


class PassportImageExportError(ValueError):
    """Base error for a ZIP export that cannot be produced safely."""


class MissingPassportImagesError(PassportImageExportError):
    """Raised when a submitted passenger is missing compulsory source images."""


class PassportImageExportLimitError(PassportImageExportError):
    """Raised when an export exceeds its bounded resource limits."""


class PassportImageZipExporter:
    """Build a collision-safe ZIP in a memory-to-disk spooled file."""

    MAX_SUBMISSIONS = 5_000
    MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
    SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
    STORAGE_FETCH_BATCH_SIZE = 8

    async def export_group(
        self,
        submissions: list[PassportSubmission],
        *,
        group_name: str,
        staff_code_enabled: bool,
        storage: IObjectStorageRepository,
        agent_employee_code_enabled: bool = False,
        crop_metadata: Mapping[object, Mapping[PassportImageType, PassportImageCrop]] | None = None,
        zone_names: Mapping[object, str] | None = None,
        namespace_submissions: list[PassportSubmission] | None = None,
    ) -> tuple[BinaryIO, int, int]:
        if len(submissions) > self.MAX_SUBMISSIONS:
            raise PassportImageExportLimitError(
                f"Image export is limited to {self.MAX_SUBMISSIONS} passengers at a time."
            )

        namespace = submissions if namespace_submissions is None else namespace_submissions
        if len(namespace) > self.MAX_SUBMISSIONS:
            raise PassportImageExportLimitError(
                f"Image export is limited to {self.MAX_SUBMISSIONS} passengers at a time."
            )
        payload_by_id = {submission.id: submission for submission in submissions}
        namespace_ids = {submission.id for submission in namespace}
        if not set(payload_by_id).issubset(namespace_ids):
            raise PassportImageExportError(
                "Every exported passenger must exist in the naming namespace."
            )

        resolved_zones = {item.id: self._zone_name(item, zone_names) for item in namespace}
        use_zone_folders = any(resolved_zones.values())
        zone_folders = self._zone_folders(resolved_zones.values()) if use_zone_folders else {}
        ordered_namespace = sorted(
            namespace,
            key=lambda item: (
                (resolved_zones[item.id].casefold() if resolved_zones[item.id] else "\uffff")
                if use_zone_folders
                else "",
                self._passenger_folder_base(
                    item,
                    staff_code_enabled=staff_code_enabled,
                    agent_employee_code_enabled=agent_employee_code_enabled,
                ).casefold(),
                str(item.id),
            ),
        )
        missing = [
            item.client_name
            for item in submissions
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
        written_zone_folders: set[str] = set()
        image_specs: list[_ArchiveImageSpec] = []

        try:
            with zipfile.ZipFile(
                spool, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True
            ) as archive:
                archive.writestr(self._zip_info(f"{root}/", is_directory=True), b"")
                for namespace_submission in ordered_namespace:
                    zone_folder = ""
                    if use_zone_folders:
                        zone_name = resolved_zones[namespace_submission.id]
                        zone_folder = (
                            zone_folders[zone_name.casefold()]
                            if zone_name
                            else _UNASSIGNED_ZONE_FOLDER
                        )

                    base_folder = self._passenger_folder_base(
                        namespace_submission,
                        staff_code_enabled=staff_code_enabled,
                        agent_employee_code_enabled=agent_employee_code_enabled,
                    )
                    passenger_folder = base_folder
                    occurrence = 1
                    folder_path = (
                        f"{zone_folder}/{passenger_folder}" if zone_folder else passenger_folder
                    )
                    while folder_path.casefold() in used_folders:
                        occurrence += 1
                        passenger_folder = f"{base_folder}_{occurrence}"
                        folder_path = (
                            f"{zone_folder}/{passenger_folder}" if zone_folder else passenger_folder
                        )
                    used_folders.add(folder_path.casefold())

                    submission = payload_by_id.get(namespace_submission.id)
                    if submission is None:
                        # Still reserve the folder name. This keeps a subset ZIP
                        # byte-for-byte compatible with the full export's naming
                        # namespace and prevents overwrites when archives merge.
                        continue
                    if use_zone_folders and zone_folder.casefold() not in written_zone_folders:
                        archive.writestr(
                            self._zip_info(
                                f"{root}/{zone_folder}/",
                                is_directory=True,
                            ),
                            b"",
                        )
                        written_zone_folders.add(zone_folder.casefold())

                    images = [
                        (
                            "passportfront",
                            PassportImageType.PASSPORT_FRONT,
                            submission.image_s3_key,
                        ),
                        (
                            "passportback",
                            PassportImageType.PASSPORT_BACK,
                            submission.passport_back_s3_key,
                        ),
                    ]
                    if submission.passport_photo_s3_key:
                        images.insert(
                            0,
                            (
                                "visaimage",
                                PassportImageType.VISA_PHOTO,
                                submission.passport_photo_s3_key,
                            ),
                        )

                    submission_crops = crop_metadata.get(submission.id, {}) if crop_metadata else {}
                    for label, image_type, storage_key in images:
                        if not storage_key:
                            continue
                        crop = submission_crops.get(image_type)
                        effective_crop = (
                            crop
                            if crop and crop.active and crop.source_storage_key == storage_key
                            else None
                        )
                        image_specs.append(
                            _ArchiveImageSpec(
                                path_stem=(f"{root}/{folder_path}/{passenger_folder}_{label}"),
                                storage_key=storage_key,
                                crop=effective_crop,
                            )
                        )

                for offset in range(0, len(image_specs), self.STORAGE_FETCH_BATCH_SIZE):
                    loaded_images = await self._load_batch(
                        image_specs[offset : offset + self.STORAGE_FETCH_BATCH_SIZE],
                        storage=storage,
                    )
                    for loaded_image in loaded_images:
                        total_bytes += len(loaded_image.content)
                        if total_bytes > self.MAX_UNCOMPRESSED_BYTES:
                            raise PassportImageExportLimitError(
                                "Image export exceeds the 2 GB uncompressed safety limit."
                            )
                        archive.writestr(
                            self._zip_info(loaded_image.path),
                            loaded_image.content,
                        )
                        entry_count += 1

            spool.seek(0)
            return spool, entry_count, total_bytes
        except Exception:
            spool.close()
            raise

    async def _load_batch(
        self,
        specs: list[_ArchiveImageSpec],
        *,
        storage: IObjectStorageRepository,
    ) -> list[_LoadedArchiveImage]:
        tasks = [asyncio.create_task(self._load_image(spec, storage=storage)) for spec in specs]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    @staticmethod
    async def _load_image(
        spec: _ArchiveImageSpec,
        *,
        storage: IObjectStorageRepository,
    ) -> _LoadedArchiveImage:
        extension = safe_storage_extension(spec.storage_key)
        crop = spec.crop
        if crop and crop.derived_storage_key:
            try:
                content = await storage.get_file(crop.derived_storage_key)
                extension = ".jpg"
            except StorageError:
                render_source_key = crop.edit_source_storage_key or spec.storage_key
                original = await storage.get_file(render_source_key)
                rendered = await asyncio.to_thread(
                    render_saved_passport_image_crop,
                    original,
                    crop,
                )
                content = rendered.content
                extension = rendered.extension
        else:
            content = await storage.get_file(spec.storage_key)
        return _LoadedArchiveImage(
            path=f"{spec.path_stem}{extension}",
            content=content,
        )

    @staticmethod
    def _passenger_folder_base(
        submission: PassportSubmission,
        *,
        staff_code_enabled: bool,
        agent_employee_code_enabled: bool,
    ) -> str:
        client_name = sanitize_zip_component(submission.client_name, fallback="CLIENT")
        metadata = submission.staff_metadata or {}
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        if agent_employee_code_enabled:
            agent_employee_code = prefixed_agent_employee_code(
                fields.get("agent_employee_type") or metadata.get("agent_employee_type"),
                fields.get("agent_employee_code") or metadata.get("agent_employee_code"),
            )
            safe_agent_employee_code = (
                sanitize_zip_component(agent_employee_code, fallback="")
                if agent_employee_code
                else ""
            )
            if safe_agent_employee_code:
                return f"{safe_agent_employee_code}_{client_name}"
        if staff_code_enabled:
            staff_code = prefixed_staff_code(metadata.get("staff_code") or fields.get("staff_code"))
            safe_staff_code = sanitize_zip_component(staff_code, fallback="") if staff_code else ""
            if safe_staff_code:
                return f"{safe_staff_code}_{client_name}"
        return client_name

    @staticmethod
    def _zone_name(
        submission: PassportSubmission,
        zone_names: Mapping[object, str] | None,
    ) -> str:
        def normalize(value: object) -> str:
            normalized = " ".join(str(value or "").strip().split())
            if normalized.casefold() in {"null", "none", "n/a", "na"}:
                return ""
            return normalized

        matched_zone = normalize((zone_names or {}).get(submission.id))
        if matched_zone:
            return matched_zone
        return normalize((submission.staff_metadata or {}).get("zone_name"))

    @staticmethod
    def _zone_folders(zone_names: Iterable[str]) -> dict[str, str]:
        names = [zone_name for zone_name in zone_names if isinstance(zone_name, str)]
        result: dict[str, str] = {}
        used_folders = (
            {_UNASSIGNED_ZONE_FOLDER.casefold()}
            if any(not zone_name for zone_name in names)
            else set()
        )
        for zone_name in sorted(
            set(filter(None, names)),
            key=lambda value: (value.casefold(), value),
        ):
            zone_key = zone_name.casefold()
            if zone_key in result:
                continue
            base_folder = sanitize_zip_component(zone_name, fallback="ZONE")
            zone_folder = base_folder
            occurrence = 1
            while zone_folder.casefold() in used_folders:
                occurrence += 1
                zone_folder = f"{base_folder}_{occurrence}"
            result[zone_key] = zone_folder
            used_folders.add(zone_folder.casefold())
        return result

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
    ascii_component = (
        unicodedata.normalize("NFKD", component).encode("ascii", "ignore").decode("ascii")
    )
    ascii_component = re.sub(r"[^A-Za-z0-9._ -]+", "_", ascii_component).strip(" ._") or "GROUP"
    return f"{ascii_component[:100]}_PASSPORT_IMAGES.zip"
