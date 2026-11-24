"""Private photo preparation operations."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select

from app.application.my_photos.errors import MyPhotosConflict
from app.application.my_photos.states import (
    MEDIA_DELIVERY_READY_STATES,
    MEDIA_REHYDRATABLE_STATES,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoJobModel,
)
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.delivery_assets import (
    MyPhotosDeliveryAssets,
)
from app.infrastructure.my_photos.delivery_context import (
    MyPhotosDeliveryContext,
)
from app.infrastructure.my_photos.telemetry import my_photos_metrics
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosPrepareRequest,
    MyPhotosPrepareResponse,
)


class MyPhotosMediaPreparation:
    def __init__(self, context: MyPhotosDeliveryContext, assets: MyPhotosDeliveryAssets) -> None:
        self._context = context
        self._assets = assets

    async def prepare_media(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        request: MyPhotosPrepareRequest,
    ) -> MyPhotosPrepareResponse:
        identity = self._context.require_passenger(claims, trip)
        await self._context.lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        gallery = await self._context.ready_gallery(claims.agency_id, trip.group.id)
        asset = (await self._assets._authorized_assets(identity.id, gallery, [asset_id])).get(
            asset_id
        )
        if asset is None:
            raise EntityNotFoundError("My Photos asset", asset_id)
        request_fingerprint = hashlib.sha256(
            f"{asset.id}:{request.quality}".encode("ascii")
        ).hexdigest()
        existing = (
            await self._context.session.execute(
                select(MyPhotoJobModel).where(
                    MyPhotoJobModel.gallery_id == gallery.id,
                    MyPhotoJobModel.job_type == "prepare_media",
                    MyPhotoJobModel.idempotency_key == request.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if (
                existing.media_asset_id != asset.id
                or existing.request_fingerprint != request_fingerprint
            ):
                raise MyPhotosConflict(
                    "MY_PHOTOS_IDEMPOTENCY_CONFLICT",
                    "This request key was already used for a different photo.",
                )
            return MyPhotosPrepareResponse(
                asset_id=asset.id,
                state=(
                    "delivery_available"
                    if asset.availability_state in MEDIA_DELIVERY_READY_STATES
                    else "preparing_delivery"
                ),
                preparation_id=(
                    None if asset.availability_state in MEDIA_DELIVERY_READY_STATES else existing.id
                ),
                retry_after_seconds=(
                    None if asset.availability_state in MEDIA_DELIVERY_READY_STATES else 60
                ),
            )
        if asset.availability_state in MEDIA_DELIVERY_READY_STATES:
            return MyPhotosPrepareResponse(
                asset_id=asset.id,
                state="delivery_available",
                preparation_id=None,
                retry_after_seconds=None,
            )
        if (
            asset.availability_state not in MEDIA_REHYDRATABLE_STATES
            or asset.archive_reference is None
        ):
            raise MyPhotosConflict(
                "MY_PHOTOS_MEDIA_PROCESSING",
                "This photo is not ready for delivery yet.",
            )
        job = MyPhotoJobModel(
            gallery_id=gallery.id,
            media_asset_id=asset.id,
            agency_id=gallery.agency_id,
            group_id=gallery.group_id,
            job_type="prepare_media",
            status="queued",
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
            checkpoint_cursor=request.quality,
            max_attempts=self._context.settings.my_photos.job_max_attempts,
            total_count=1,
            correlation_id=uuid.uuid4().hex,
        )
        self._context.session.add(job)
        asset.availability_state = "rehydration_requested"
        my_photos_metrics.rehydration_requested()
        await self._context.session.flush()
        await record_my_photos_audit(
            self._context.session,
            action="my_photos_rehydration_requested",
            agency_id=claims.agency_id,
            group_id=trip.group.id,
            outcome=request.quality,
            gallery_revision=gallery.published_revision,
        )
        return MyPhotosPrepareResponse(
            asset_id=asset.id,
            state="rehydration_requested",
            preparation_id=job.id,
            retry_after_seconds=60,
        )
