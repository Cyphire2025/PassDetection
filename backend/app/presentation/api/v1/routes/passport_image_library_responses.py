"""Passport image library responses."""

from __future__ import annotations

import uuid

from app.core.config.settings import get_settings
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
)
from app.domain.value_objects.passport_image_library import PassportImageLibraryItem
from app.presentation.api.v1.schemas.passport_image_library_schemas import (
    PassportImageLibraryItemResponse,
)


def _library_image_url(
    *,
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    item_id: uuid.UUID,
) -> str:
    return (
        f"{get_settings().api_v1_prefix}/passports/{submission_id}/images/{image_type.value}/"
        f"library/{item_id}/image"
    )


def _library_item_response(
    *,
    item: PassportImageLibraryItem,
    authoritative_source_key: str,
    current_edit_source_key: str | None,
) -> PassportImageLibraryItemResponse:
    is_current = item.storage_key == current_edit_source_key or (
        current_edit_source_key is None and item.storage_key == authoritative_source_key
    )
    return PassportImageLibraryItemResponse(
        id=item.id,
        image_type=item.image_type.value,
        image_url=_library_image_url(
            submission_id=item.submission_id,
            image_type=item.image_type,
            item_id=item.id,
        ),
        source=item.source.value,
        created_at=item.created_at,
        is_current=is_current,
        prompt=item.prompt,
        model=item.model,
    )
