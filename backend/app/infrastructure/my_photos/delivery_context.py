"""Typed shared dependencies for the existing private photo delivery workflow."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.config.settings import Settings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryModel,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle

PassengerResolver = Callable[
    [MobileAccessClaims, AuthorizedMobileTrip], MobilePassengerIdentityModel
]

GalleryResolver = Callable[[uuid.UUID, uuid.UUID], Awaitable[MyPhotoGalleryModel]]

PassengerLocker = Callable[[uuid.UUID, uuid.UUID, uuid.UUID], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class MyPhotosDeliveryContext:
    session: AsyncSession
    settings: Settings
    providers: MyPhotosProviderBundle
    require_passenger: PassengerResolver
    ready_gallery: GalleryResolver
    lock_passenger_identity: PassengerLocker
