"""Typed shared My Photos authorization, current-state queries and policy gates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.errors import (
    MyPhotosUnavailable,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.config.settings import Settings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.liveness_validation import (
    _as_utc,
    _require_current_consent,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle


@dataclass(frozen=True, slots=True)
class MyPhotosContext:
    session: AsyncSession
    settings: Settings
    providers: MyPhotosProviderBundle

    async def _gallery(
        self, agency_id: uuid.UUID, group_id: uuid.UUID
    ) -> MyPhotoGalleryModel | None:
        return (
            await self.session.execute(
                select(MyPhotoGalleryModel)
                .where(
                    MyPhotoGalleryModel.agency_id == agency_id,
                    MyPhotoGalleryModel.group_id == group_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def _ready_gallery(
        self, agency_id: uuid.UUID, group_id: uuid.UUID
    ) -> MyPhotoGalleryModel:
        gallery = await self._gallery(agency_id, group_id)
        if gallery is None or not gallery.feature_enabled:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_FEATURE_UNAVAILABLE", "My Photos is not available for this trip."
            )
        window_state = self._gallery_window_state(gallery, datetime.now(tz=UTC))
        if window_state == "not_started":
            raise MyPhotosUnavailable(
                "MY_PHOTOS_NOT_AVAILABLE_YET", "My Photos is not available for this trip yet."
            )
        if window_state == "expired":
            raise MyPhotosUnavailable(
                "MY_PHOTOS_ACCESS_EXPIRED", "Access to this trip's My Photos gallery has expired."
            )
        if gallery.status != "ready":
            raise MyPhotosUnavailable(
                "MY_PHOTOS_GALLERY_NOT_READY", "This trip's gallery is not ready yet."
            )
        return gallery

    @staticmethod
    def _gallery_window_state(gallery: MyPhotoGalleryModel | None, now: datetime) -> str:
        if gallery is None:
            return "not_started"
        if gallery.availability_starts_at is not None and now < _as_utc(
            gallery.availability_starts_at
        ):
            return "not_started"
        # The end instant is exclusive: authorizations and reads fail closed at
        # exactly availability_ends_at, not one request later.
        if gallery.availability_ends_at is not None and now >= _as_utc(
            gallery.availability_ends_at
        ):
            return "expired"
        return "active"

    async def _enrollment(
        self,
        passenger_identity_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> MyPhotoEnrollmentModel | None:
        statement = select(MyPhotoEnrollmentModel).where(
            MyPhotoEnrollmentModel.passenger_identity_id == passenger_identity_id,
            MyPhotoEnrollmentModel.group_id == group_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (
            await self.session.execute(statement.execution_options(populate_existing=True))
        ).scalar_one_or_none()

    async def _lock_passenger_identity(
        self,
        passenger_identity_id: uuid.UUID,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> None:
        """Serialize first-write idempotent mutations on an existing parent row."""

        locked_id = (
            await self.session.execute(
                select(MobilePassengerIdentityModel.id)
                .where(
                    MobilePassengerIdentityModel.id == passenger_identity_id,
                    MobilePassengerIdentityModel.agency_id == agency_id,
                    MobilePassengerIdentityModel.group_id == group_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if locked_id is None:
            raise AuthorizationError("Passenger resource is not available")

    async def _required_current_enrollment(
        self, passenger_identity_id: uuid.UUID, group_id: uuid.UUID
    ) -> MyPhotoEnrollmentModel:
        enrollment = _require_current_consent(
            await self._enrollment(passenger_identity_id, group_id, for_update=True),
            self.settings.my_photos.consent_version,
        )
        now = datetime.now(tz=UTC)
        if (
            enrollment.status == "cooldown"
            and enrollment.cooldown_until is not None
            and _as_utc(enrollment.cooldown_until) <= now
        ):
            enrollment.status = "ready"
            enrollment.attempt_count = 0
            enrollment.cooldown_until = None
        return enrollment

    async def _latest_search(
        self, passenger_identity_id: uuid.UUID, group_id: uuid.UUID
    ) -> MyPhotoSearchRunModel | None:
        return (
            await self.session.execute(
                select(MyPhotoSearchRunModel)
                .where(
                    MyPhotoSearchRunModel.passenger_identity_id == passenger_identity_id,
                    MyPhotoSearchRunModel.group_id == group_id,
                )
                .order_by(MyPhotoSearchRunModel.created_at.desc(), MyPhotoSearchRunModel.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    def _require_face_providers(self) -> None:
        if not self.providers.liveness.ready or not self.providers.face_search.ready:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face Scan is not available yet."
            )

    @staticmethod
    def _require_passenger(
        claims: MobileAccessClaims, trip: AuthorizedMobileTrip
    ) -> MobilePassengerIdentityModel:
        if claims.principal_type != "passenger" or trip.passenger_identity is None:
            raise AuthorizationError("My Photos is available only to the signed-in passenger")
        if trip.passenger_identity.id != claims.principal_id:
            raise AuthorizationError("Passenger resource is not available")
        return trip.passenger_identity
