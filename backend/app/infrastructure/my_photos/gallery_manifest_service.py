"""Compose the four bounded gallery manifest workflows over explicit resources."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.infrastructure.my_photos.gallery_manifest_cancellation import cancel_manifest
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestLocator as GalleryManifestLocator,
)
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestRequest as GalleryManifestRequest,
)
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestResult as GalleryManifestResult,
)
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestStatus as GalleryManifestStatus,
)
from app.infrastructure.my_photos.gallery_manifest_finalization import finalize_manifest
from app.infrastructure.my_photos.gallery_manifest_registration import register_batch
from app.infrastructure.my_photos.gallery_manifest_status import manifest_status
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle


class GalleryManifestRegistrationService:
    """Stage idempotent batches and finalize exactly one atomic gallery revision."""

    def __init__(
        self, session: AsyncSession, *, settings: Settings, providers: MyPhotosProviderBundle
    ) -> None:
        self._session = session
        self._settings = settings
        self._providers = providers

    def _context(self) -> GalleryManifestContext:
        return GalleryManifestContext(self._session, self._settings, self._providers)

    async def manifest_status(
        self, *, actor: User, mfa_verified_at: datetime, locator: GalleryManifestLocator
    ) -> GalleryManifestStatus:
        return await manifest_status(
            self._context(), actor=actor, mfa_verified_at=mfa_verified_at, locator=locator
        )

    async def cancel_manifest(
        self, *, actor: User, mfa_verified_at: datetime, locator: GalleryManifestLocator
    ) -> GalleryManifestStatus:
        return await cancel_manifest(
            self._context(), actor=actor, mfa_verified_at=mfa_verified_at, locator=locator
        )

    async def register_batch(
        self,
        *,
        actor: User,
        mfa_verified_at: datetime,
        request: GalleryManifestRequest,
        dispatch: Callable[[uuid.UUID], None],
    ) -> GalleryManifestResult:
        return await register_batch(
            self._context(),
            actor=actor,
            mfa_verified_at=mfa_verified_at,
            request=request,
            dispatch=dispatch,
        )

    async def finalize_manifest(
        self,
        *,
        actor: User,
        mfa_verified_at: datetime,
        request: GalleryManifestRequest,
        dispatch: Callable[[uuid.UUID], None],
        batch_replay: bool = False,
    ) -> GalleryManifestResult:
        return await finalize_manifest(
            self._context(),
            actor=actor,
            mfa_verified_at=mfa_verified_at,
            request=request,
            dispatch=dispatch,
            batch_replay=batch_replay,
        )


GalleryManifestRegistrationService.__module__ = "app.infrastructure.my_photos.gallery_ingestion"
