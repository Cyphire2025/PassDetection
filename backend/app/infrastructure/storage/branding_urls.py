"""Versioned, authenticated image URLs; storage keys never leave the server."""

import uuid
from typing import Literal

BrandingKind = Literal["company-logo", "group-banner"]


def image_version(key: str | None) -> str:
    return key.rsplit("/", 1)[-1].split(".", 1)[0] if key else ""


def branding_image_url(kind: BrandingKind, owner_id: uuid.UUID, agency_id: uuid.UUID, key: str | None) -> str | None:
    if not key:
        return None
    return f"/api/v1/branding/{kind}/{owner_id}?agency_id={agency_id}&v={image_version(key)}"
