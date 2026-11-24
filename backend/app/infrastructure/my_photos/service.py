"""Authorized My Photos application service and explicit state transitions."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.providers import (
    DeliveryResolution,
)
from app.application.my_photos.states import (
    MatchFilter,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.config.settings import Settings, get_settings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoLivenessSessionModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.catalog_service import MyPhotosCatalogService
from app.infrastructure.my_photos.context import MyPhotosContext
from app.infrastructure.my_photos.delivery_service import MyPhotosDeliveryService
from app.infrastructure.my_photos.enrollment_service import MyPhotosEnrollmentService
from app.infrastructure.my_photos.liveness_service import MyPhotosLivenessService
from app.infrastructure.my_photos.liveness_store import MyPhotosLivenessStore
from app.infrastructure.my_photos.liveness_validation import _as_utc as _as_utc
from app.infrastructure.my_photos.liveness_validation import (
    _liveness_processing as _liveness_processing,
)
from app.infrastructure.my_photos.liveness_validation import (
    _provider_claim_active as _provider_claim_active,
)
from app.infrastructure.my_photos.liveness_validation import (
    _require_current_consent as _require_current_consent,
)
from app.infrastructure.my_photos.liveness_validation import (
    _validated_liveness_result as _validated_liveness_result,
)
from app.infrastructure.my_photos.liveness_validation import (
    _validated_liveness_session_handle as _validated_liveness_session_handle,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle, build_provider_bundle
from app.infrastructure.my_photos.reference_lifecycle import MyPhotosReferenceLifecycle
from app.infrastructure.my_photos.responses import _completion_response, _search_response
from app.infrastructure.my_photos.summary_projector import MyPhotosSummaryProjector
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosConsentRequest,
    MyPhotosDeleteEnrollmentRequest,
    MyPhotosDeleteEnrollmentResponse,
    MyPhotosDownloadAuthorizationRequest,
    MyPhotosDownloadAuthorizationResponse,
    MyPhotosDownloadPlanResponse,
    MyPhotosFeedbackRequest,
    MyPhotosFeedbackResponse,
    MyPhotosLivenessCompleteRequest,
    MyPhotosLivenessCompleteResponse,
    MyPhotosLivenessSessionResponse,
    MyPhotosLivenessStartRequest,
    MyPhotosPhotoPageResponse,
    MyPhotosPrepareRequest,
    MyPhotosPrepareResponse,
    MyPhotosSearchResponse,
    MyPhotosSummaryResponse,
)


class MyPhotosService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        providers: MyPhotosProviderBundle | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._providers = providers or build_provider_bundle(self._settings)
        self._context = MyPhotosContext(session, self._settings, self._providers)
        self._delivery = MyPhotosDeliveryService(
            session,
            settings=self._settings,
            providers=self._providers,
            require_passenger=self._context._require_passenger,
            ready_gallery=self._context._ready_gallery,
            lock_passenger_identity=self._context._lock_passenger_identity,
        )
        self._summary = MyPhotosSummaryProjector(
            session,
            settings=self._settings,
            providers=self._providers,
            gallery_window_state=self._context._gallery_window_state,
            search_response=_search_response,
        )
        references = MyPhotosReferenceLifecycle(self._context)
        self._liveness = MyPhotosLivenessService(
            self._context,
            state=MyPhotosLivenessStore(self._context),
            references=references,
        )
        self._enrollments = MyPhotosEnrollmentService(
            self._context,
            references=references,
            summary=self._summary,
        )
        self._catalog = MyPhotosCatalogService(self._context, delivery=self._delivery)

    async def summary(
        self, *, claims: MobileAccessClaims, trip: AuthorizedMobileTrip
    ) -> MyPhotosSummaryResponse:
        identity = self._context._require_passenger(claims, trip)
        gallery = await self._context._gallery(claims.agency_id, trip.group.id)
        enrollment = await self._context._enrollment(identity.id, trip.group.id)
        search = await self._context._latest_search(identity.id, trip.group.id)
        return await self._summary.build(
            group_name=trip.group.name,
            group_id=trip.group.id,
            gallery=gallery,
            enrollment=enrollment,
            search=search,
            passenger_identity_id=identity.id,
        )

    async def accept_consent(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosConsentRequest,
    ) -> MyPhotosSummaryResponse:
        return await self._enrollments.accept_consent(
            claims=claims,
            trip=trip,
            request=request,
        )

    async def start_liveness(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosLivenessStartRequest,
    ) -> MyPhotosLivenessSessionResponse:
        return await self._liveness.start_liveness(
            claims=claims,
            trip=trip,
            request=request,
        )

    async def complete_liveness(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        session_id: uuid.UUID,
        request: MyPhotosLivenessCompleteRequest,
    ) -> MyPhotosLivenessCompleteResponse:
        return await self._liveness.complete_liveness(
            claims=claims,
            trip=trip,
            session_id=session_id,
            request=request,
        )

    async def search_status(
        self, *, claims: MobileAccessClaims, trip: AuthorizedMobileTrip
    ) -> MyPhotosSearchResponse:
        identity = self._context._require_passenger(claims, trip)
        await self._context._ready_gallery(claims.agency_id, trip.group.id)
        search = await self._context._latest_search(identity.id, trip.group.id)
        return MyPhotosSearchResponse(search=_search_response(search))

    async def photo_page(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        match_filter: MatchFilter,
        cursor: str | None,
        limit: int,
    ) -> MyPhotosPhotoPageResponse:
        return await self._catalog.photo_page(
            claims=claims,
            trip=trip,
            match_filter=match_filter,
            cursor=cursor,
            limit=limit,
        )

    async def record_feedback(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        request: MyPhotosFeedbackRequest,
    ) -> MyPhotosFeedbackResponse:
        return await self._catalog.record_feedback(
            claims=claims,
            trip=trip,
            asset_id=asset_id,
            request=request,
        )

    async def delete_enrollment(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosDeleteEnrollmentRequest,
    ) -> MyPhotosDeleteEnrollmentResponse:
        return await self._enrollments.delete_enrollment(
            claims=claims,
            trip=trip,
            request=request,
        )

    async def prepare_media(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        request: MyPhotosPrepareRequest,
    ) -> MyPhotosPrepareResponse:
        return await self._delivery.prepare_media(
            claims=claims, trip=trip, asset_id=asset_id, request=request
        )

    async def authorize_downloads(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosDownloadAuthorizationRequest,
    ) -> MyPhotosDownloadAuthorizationResponse:
        return await self._delivery.authorize_downloads(claims=claims, trip=trip, request=request)

    async def download_plan(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
    ) -> MyPhotosDownloadPlanResponse:
        return await self._delivery.download_plan(claims=claims, trip=trip)

    async def development_download_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> tuple[bytes, str, str]:
        return await self._delivery.development_download_content(
            claims=claims, trip=trip, authorization_id=authorization_id
        )

    async def production_download_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> DeliveryResolution:
        return await self._delivery.production_download_location(
            claims=claims,
            trip=trip,
            authorization_id=authorization_id,
        )

    async def download_content_or_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> tuple[bytes, str, str] | DeliveryResolution:
        if self._providers.provider_name == "aws":
            return await self.production_download_location(
                claims=claims,
                trip=trip,
                authorization_id=authorization_id,
            )
        return await self.development_download_content(
            claims=claims,
            trip=trip,
            authorization_id=authorization_id,
        )

    async def development_preview_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: str,
    ) -> tuple[bytes, str]:
        return await self._delivery.development_preview_content(
            claims=claims, trip=trip, asset_id=asset_id, variant=variant
        )

    async def preview_content_or_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: Literal["thumbnail", "preview"],
    ) -> tuple[bytes, str] | DeliveryResolution:
        return await self._delivery.preview_content_or_location(
            claims=claims,
            trip=trip,
            asset_id=asset_id,
            variant=variant,
        )

    def _completion_response(
        self,
        session: MyPhotoLivenessSessionModel,
        enrollment: MyPhotoEnrollmentModel,
        search: MyPhotoSearchRunModel | None,
    ) -> MyPhotosLivenessCompleteResponse:
        return _completion_response(session, enrollment, search)
