"""Legacy public namespace for manifest workflows and their annotation types."""

from __future__ import annotations

import uuid as uuid
from collections.abc import Mapping as Mapping
from datetime import datetime as datetime
from typing import Literal as Literal

from app.application.my_photos.providers import MediaAvailabilityResult as MediaAvailabilityResult
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestAsset as GalleryManifestAsset,
)
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
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestVariant as GalleryManifestVariant,
)
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    ManifestDispatchState as ManifestDispatchState,
)
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    ManifestState as ManifestState,
)
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    _VerifiedAsset as _VerifiedAsset,
)
from app.infrastructure.my_photos.gallery_manifest_service import (
    GalleryManifestRegistrationService as GalleryManifestRegistrationService,
)

__all__ = [
    "GalleryManifestAsset",
    "GalleryManifestLocator",
    "GalleryManifestRegistrationService",
    "GalleryManifestRequest",
    "GalleryManifestResult",
    "GalleryManifestStatus",
    "GalleryManifestVariant",
]
