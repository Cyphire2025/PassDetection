"""Gallery manifest queries owner."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select

from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryManifestBatchModel,
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
)
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestLocator,
    GalleryManifestRequest,
)


async def _load_scope(
    ctx: GalleryManifestContext,
    request: GalleryManifestRequest | GalleryManifestLocator,
    *,
    lock: bool,
) -> tuple[ClientGroupModel, GCGroupAccessModel]:
    statement = (
        select(ClientGroupModel, GCGroupAccessModel)
        .join(
            GCGroupAccessModel,
            and_(
                GCGroupAccessModel.group_id == ClientGroupModel.id,
                GCGroupAccessModel.agency_id == ClientGroupModel.agency_id,
            ),
        )
        .where(
            ClientGroupModel.id == request.group_id,
            ClientGroupModel.agency_id == request.agency_id,
            ClientGroupModel.status.in_(("active", "closed")),
            GCGroupAccessModel.is_enabled.is_(True),
            GCGroupAccessModel.passenger_access_enabled.is_(True),
            GCGroupAccessModel.revoked_at.is_(None),
        )
    )
    if lock:
        statement = statement.with_for_update()
    row = (await ctx.session.execute(statement)).first()
    if row is None:
        raise EntityNotFoundError("My Photos trip", request.group_id)
    return (row[0], row[1])


async def _locked_gallery(
    ctx: GalleryManifestContext,
    request: GalleryManifestRequest | GalleryManifestLocator,
    *,
    lock: bool = True,
) -> MyPhotoGalleryModel | None:
    statement = select(MyPhotoGalleryModel).where(
        MyPhotoGalleryModel.agency_id == request.agency_id,
        MyPhotoGalleryModel.group_id == request.group_id,
    )
    if lock:
        statement = statement.with_for_update()
    return (await ctx.session.execute(statement)).scalar_one_or_none()


async def _locked_manifest(
    ctx: GalleryManifestContext, gallery_id: uuid.UUID, manifest_identity: str, *, lock: bool = True
) -> MyPhotoGalleryManifestModel | None:
    statement = select(MyPhotoGalleryManifestModel).where(
        MyPhotoGalleryManifestModel.gallery_id == gallery_id,
        MyPhotoGalleryManifestModel.manifest_identity == manifest_identity,
    )
    if lock:
        statement = statement.with_for_update()
    return (await ctx.session.execute(statement)).scalar_one_or_none()


async def _locked_batch(
    ctx: GalleryManifestContext, manifest_id: uuid.UUID, batch_index: int
) -> MyPhotoGalleryManifestBatchModel | None:
    return (
        await ctx.session.execute(
            select(MyPhotoGalleryManifestBatchModel)
            .where(
                MyPhotoGalleryManifestBatchModel.manifest_id == manifest_id,
                MyPhotoGalleryManifestBatchModel.batch_index == batch_index,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()


async def _job_for_manifest(
    ctx: GalleryManifestContext,
    gallery_id: uuid.UUID,
    manifest_identity: str,
    *,
    lock: bool = False,
) -> MyPhotoJobModel | None:
    statement = select(MyPhotoJobModel).where(
        MyPhotoJobModel.gallery_id == gallery_id,
        MyPhotoJobModel.job_type == "index_gallery",
        MyPhotoJobModel.idempotency_key == manifest_identity,
    )
    if lock:
        statement = statement.with_for_update()
    return (await ctx.session.execute(statement)).scalar_one_or_none()
