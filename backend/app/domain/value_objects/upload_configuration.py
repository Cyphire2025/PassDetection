"""Versioned public-upload controls, with explicit legacy defaults."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.exceptions.exceptions import ValidationError

MAX_PUBLIC_DOCUMENT_BYTES = 2 * 1024 * 1024
PassportPage = Literal["cover", "back_cover", "front", "back"]
PASSPORT_PAGE_ORDER: tuple[PassportPage, ...] = ("cover", "back_cover", "front", "back")
PASSPORT_PAGE_LABELS = {
    "cover": "Passport front cover",
    "back_cover": "Passport back cover",
    "front": "Passport personal details page",
    "back": "Passport address details page",
}
RequiredField = Literal[
    "base_city", "nearest_domestic_airport", "departure_city", "staff_code",
    "agent_employee_code", "designation", "agency_dealership_name", "meal_preference",
    "relation_with_qualifier",
]


def _default_passport_pages() -> list[PassportPage]:
    return ["front", "back"]


class UploadConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    passport_enabled: bool = True
    passport_required: bool = True
    passport_live_scan: bool = True
    passport_upload_pages: list[PassportPage] = Field(
        default_factory=_default_passport_pages, max_length=4,
    )
    visa_photo_required: bool = True
    visa_photo_live_capture: bool = True
    visa_photo_upload: bool = True
    required_fields: dict[RequiredField, bool] = Field(default_factory=dict)
    agent_employee_code_label: str = Field(default="Agent/Employee Code", min_length=1, max_length=100)
    agency_dealership_name_label: str = Field(default="Agency/Dealership Name", min_length=1, max_length=100)

    @field_validator("passport_upload_pages")
    @classmethod
    def order_pages(cls, pages: list[PassportPage]) -> list[PassportPage]:
        if len(pages) != len(set(pages)):
            raise ValueError("Select each passport page only once.")
        return [page for page in PASSPORT_PAGE_ORDER if page in pages]

    def required(self, field: RequiredField) -> bool:
        return self.required_fields.get(field, True)


def configuration_for(group: Any) -> UploadConfiguration:
    return UploadConfiguration.model_validate(getattr(group, "upload_configuration", None) or {})


def normalize_upload_configuration(value: Mapping[str, object] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        return UploadConfiguration.model_validate(value).model_dump(mode="json")
    except ValueError as exc:
        raise ValidationError(str(exc), field="upload_configuration") from exc


def validate_capture_configuration(group: Any) -> None:
    config = configuration_for(group)
    if config.passport_enabled:
        if not config.passport_live_scan and not group.allow_files_from_device:
            raise ValidationError("Enable at least one passport collection method.", field="upload_configuration")
        if group.allow_files_from_device and not config.passport_upload_pages:
            raise ValidationError("Select at least one passport page for upload.", field="upload_configuration")
    if group.require_selfie and not (config.visa_photo_live_capture or config.visa_photo_upload):
        raise ValidationError("Enable at least one Visa Photo collection method.", field="upload_configuration")


def validate_documents(group: Any, *, pages: Mapping[str, object], mode: str, photo: object) -> None:
    """Validate both initial uploads and final submissions using authoritative settings."""
    config = configuration_for(group)
    present = {page for page, value in pages.items() if value}
    if not config.passport_enabled and present:
        raise ValidationError("Passport collection is disabled for this link.", field="file")
    if present:
        mode = group.require_allowed_acquisition_mode(mode)
        selected = {"front", "back"} if mode == "camera" else set(config.passport_upload_pages)
        if present - selected:
            raise ValidationError("A passport page was uploaded that is not requested by this link.", field="file")
        missing = selected - present
    else:
        missing = set(config.passport_upload_pages) if config.passport_enabled and config.passport_required else set()
        if config.passport_enabled and config.passport_required and not group.allow_files_from_device:
            missing = {"front", "back"}
    if missing:
        page = next(page for page in PASSPORT_PAGE_ORDER if page in missing)
        raise ValidationError(f"{PASSPORT_PAGE_LABELS[page]} is required.", field="file" if page == "front" else f"passport_{page}_file")
    if group.require_selfie and config.visa_photo_required and not photo:
        raise ValidationError("Visa Photo is required for this upload link.", field="passport_photo_file")
    if getattr(group, "upload_configuration", None) is not None and photo and not group.require_selfie:
        raise ValidationError("Visa Photo collection is disabled for this link.", field="passport_photo_file")


def validate_visa_photo_source(group: Any, *, photo: object, source: str | None) -> None:
    if not photo:
        return
    config = configuration_for(group)
    # Older clients did not identify the Visa Photo source. Preserve them only
    # when both sources remain allowed; a restricted link requires evidence of
    # the selected method in its request contract.
    if source is None and config.visa_photo_live_capture and config.visa_photo_upload:
        return
    if source not in {"camera", "file"}:
        raise ValidationError("Select an enabled Visa Photo collection method.", field="visa_photo_source")
    if source == "camera" and not config.visa_photo_live_capture:
        raise ValidationError("Live Visa Photo capture is disabled for this link.", field="visa_photo_source")
    if source == "file" and not config.visa_photo_upload:
        raise ValidationError("Visa Photo upload is disabled for this link.", field="visa_photo_source")
