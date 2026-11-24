"""Private photo assets operations."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select

from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoGalleryModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.delivery_context import (
    MyPhotosDeliveryContext,
)


class MyPhotosDeliveryAssets:
    def __init__(self, context: MyPhotosDeliveryContext) -> None:
        self._context = context

    async def _authorized_assets(
        self,
        passenger_identity_id: uuid.UUID,
        gallery: MyPhotoGalleryModel,
        asset_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, MyPhotoMediaAssetModel]:
        requested = set(asset_ids)
        assets = list(
            (
                await self._context.session.execute(
                    select(MyPhotoMediaAssetModel).where(
                        MyPhotoMediaAssetModel.id.in_(tuple(requested)),
                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                        MyPhotoMediaAssetModel.agency_id == gallery.agency_id,
                        MyPhotoMediaAssetModel.group_id == gallery.group_id,
                        MyPhotoMediaAssetModel.published_revision <= gallery.published_revision,
                        MyPhotoMediaAssetModel.processing_state != "removed",
                        MyPhotoMediaAssetModel.availability_state.notin_(("failed", "removed")),
                    )
                )
            ).scalars()
        )
        by_id = {asset.id: asset for asset in assets}
        if gallery.all_group_photos_enabled:
            return by_id
        matched_ids = set(
            (
                await self._context.session.execute(
                    select(MyPhotoMatchModel.media_asset_id).where(
                        MyPhotoMatchModel.passenger_identity_id == passenger_identity_id,
                        MyPhotoMatchModel.group_id == gallery.group_id,
                        MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                        MyPhotoMatchModel.active.is_(True),
                        MyPhotoMatchModel.media_asset_id.in_(tuple(requested)),
                    )
                )
            ).scalars()
        )
        return {asset_id: asset for asset_id, asset in by_id.items() if asset_id in matched_ids}

    async def latest_optimized_variants(
        self,
        asset_ids: list[uuid.UUID],
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> dict[uuid.UUID, MyPhotoAssetVariantModel]:
        variants = await self.latest_variants(
            asset_ids,
            agency_id=agency_id,
            group_id=group_id,
            variant_kinds=("optimized",),
        )
        return {
            asset_id: row
            for (asset_id, variant_kind), row in variants.items()
            if variant_kind == "optimized"
        }

    async def latest_variants(
        self,
        asset_ids: list[uuid.UUID],
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        variant_kinds: tuple[str, ...],
    ) -> dict[tuple[uuid.UUID, str], MyPhotoAssetVariantModel]:
        """Load latest bounded display/delivery variants in one query."""

        requested = tuple(set(asset_ids))
        if not requested:
            return {}
        if not variant_kinds or not set(variant_kinds) <= {
            "thumbnail",
            "preview",
            "analysis",
            "original",
            "optimized",
        }:
            raise ValueError("Unsupported My Photos variant kind")
        latest = (
            select(
                MyPhotoAssetVariantModel.media_asset_id.label("asset_id"),
                MyPhotoAssetVariantModel.variant_kind.label("variant_kind"),
                func.max(MyPhotoAssetVariantModel.delivery_version).label("delivery_version"),
            )
            .where(
                MyPhotoAssetVariantModel.media_asset_id.in_(requested),
                MyPhotoAssetVariantModel.agency_id == agency_id,
                MyPhotoAssetVariantModel.group_id == group_id,
                MyPhotoAssetVariantModel.variant_kind.in_(variant_kinds),
                MyPhotoAssetVariantModel.availability_state.notin_(("failed", "removed")),
            )
            .group_by(
                MyPhotoAssetVariantModel.media_asset_id,
                MyPhotoAssetVariantModel.variant_kind,
            )
            .subquery()
        )
        rows = list(
            (
                await self._context.session.execute(
                    select(MyPhotoAssetVariantModel).join(
                        latest,
                        and_(
                            latest.c.asset_id == MyPhotoAssetVariantModel.media_asset_id,
                            latest.c.delivery_version == MyPhotoAssetVariantModel.delivery_version,
                            latest.c.variant_kind == MyPhotoAssetVariantModel.variant_kind,
                        ),
                    )
                )
            ).scalars()
        )
        return {(row.media_asset_id, row.variant_kind): row for row in rows}

    async def _current_delivery_asset(
        self,
        passenger_id: uuid.UUID,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> tuple[MyPhotoGalleryModel, MyPhotoMediaAssetModel]:
        gallery = await self._context.ready_gallery(agency_id, group_id)
        asset = (await self._authorized_assets(passenger_id, gallery, [asset_id])).get(asset_id)
        if asset is None:
            raise EntityNotFoundError("My Photos asset", asset_id)
        return gallery, asset
