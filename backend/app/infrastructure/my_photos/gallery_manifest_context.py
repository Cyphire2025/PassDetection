"""Explicit resources shared by the bounded gallery manifest workflow."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle


@dataclass(frozen=True, slots=True)
class GalleryManifestContext:
    session: AsyncSession
    settings: Settings
    providers: MyPhotosProviderBundle
