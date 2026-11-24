"""Manifest validation, status and cancellation retain their critical obligations."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import FaceDeletionResult
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.gallery_ingestion import (
    GalleryManifestLocator,
    GalleryManifestRequest,
)
from tests.unit.infrastructure.test_my_photos_gallery_ingestion import (
    _asset,
    _request,
    _scope,
    _service,
)


def _valid_request():
    return _request(
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        manifest_identity="manifest-metadata",
        target_revision=1,
        assets=(_asset(0), _asset(1)),
        total_asset_count=2,
        batch_index=0,
    )


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("assets", 0, "archive_reference"), "https://example.invalid/a.jpg", "Archive references"),
        (
            ("assets", 0, "variants", 0, "storage_reference"),
            "https://example.invalid/a.jpg",
            "Variant storage references",
        ),
        (("assets", 0, "original_filename"), "directory/file.jpg", "must not contain a path"),
        (("assets", 0, "original_filename"), " file.jpg", "must be trimmed"),
        (("assets", 0, "captured_at"), "2026-08-27T12:00:00", "must carry a timezone"),
        (("assets", 0, "variants", 1, "kind"), "thumbnail", "kinds must be unique"),
        (("assets", 0, "variants", 2, "kind"), "optimized", "analysis variants are required"),
        (("availability_starts_at",), "2026-08-26T00:00:00", "start must carry a timezone"),
        (("availability_ends_at",), "2026-09-26T00:00:00", "end must carry a timezone"),
        (("availability_ends_at",), "2026-08-25T00:00:00Z", "end must follow its start"),
        (("batch_count",), 2, "batch count/index"),
        (("batch_index",), 1, "batch count/index"),
        (("total_asset_count",), 3, "batch asset count is incomplete"),
        (("assets", 1, "immutable_asset_key"), "asset-00000", "asset identities must be unique"),
        (("assets", 1, "sort_rank"), 0, "sort ranks must be unique"),
    ],
)
def test_invalid_metadata_is_rejected_at_the_actual_json_contract(path, value, message):
    data = _valid_request().model_dump(mode="json")
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError, match=message):
        GalleryManifestRequest.model_validate_json(json.dumps(data))


def test_valid_complete_metadata_still_round_trips():
    request = _valid_request()
    assert GalleryManifestRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("case", ["open_transaction", "missing_gallery", "missing_manifest"])
async def test_status_error_boundaries_preserve_transaction_ownership(db_session, case):
    agency_id, group_id, actor = await _scope(db_session)
    service = _service(db_session, (_asset(0),))
    if case == "missing_manifest":
        await service.register_batch(
            actor=actor,
            mfa_verified_at=datetime.now(UTC),
            request=_request(
                agency_id=agency_id,
                group_id=group_id,
                manifest_identity="existing-manifest",
                target_revision=1,
                assets=(_asset(0),),
                total_asset_count=1,
                batch_index=0,
            ),
            dispatch=lambda _job: None,
        )
    if case == "open_transaction":
        await db_session.execute(select(1))
    error = RuntimeError if case == "open_transaction" else EntityNotFoundError
    with pytest.raises(error):
        await service.manifest_status(
            actor=actor,
            mfa_verified_at=datetime.now(UTC),
            locator=GalleryManifestLocator(
                agency_id=agency_id,
                group_id=group_id,
                manifest_identity="missing-manifest",
            ),
        )
    assert db_session.in_transaction() is (case == "open_transaction")


@pytest.mark.parametrize(
    "outcome",
    [
        "valid",
        "missing",
        "duplicate",
        "unavailable",
        "unexpected",
        "not_configured",
    ],
)
async def test_cancel_only_removes_faces_after_exact_provider_confirmation(
    db_session,
    monkeypatch,
    outcome,
):
    agency_id, group_id, actor = await _scope(db_session)
    service = _service(db_session, (_asset(0),))
    request = _request(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity="partial-index-cleanup",
        target_revision=1,
        assets=(_asset(0),),
        total_asset_count=1,
        batch_index=0,
        finalize=True,
    )
    registered = await service.register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(UTC),
        request=request,
        dispatch=lambda _job: None,
    )
    asset_id = await db_session.scalar(
        select(MyPhotoMediaAssetModel.id).where(
            MyPhotoMediaAssetModel.gallery_id == registered.gallery_id,
        )
    )
    job = await db_session.get(MyPhotoJobModel, registered.index_job_id)
    gallery = await db_session.get(MyPhotoGalleryModel, registered.gallery_id)
    job.status, job.completed_at = "failed", datetime.now(UTC)
    gallery.status = "failed"
    face_id = uuid.uuid4()
    db_session.add(
        MyPhotoFaceOccurrenceModel(
            id=face_id,
            media_asset_id=asset_id,
            agency_id=agency_id,
            group_id=group_id,
            provider_name="aws",
            provider_face_reference="synthetic-partial-face",
            idempotency_identity="synthetic-partial-face",
            provider_model_version="7.0",
            index_version=1,
            bounding_left=0.1,
            bounding_top=0.1,
            bounding_width=0.3,
            bounding_height=0.3,
            active=True,
        )
    )
    await db_session.commit()
    provider = service._providers.face_search
    original_delete = provider.delete_faces
    calls = []

    async def delete_faces(payload):
        calls.append(payload.provider_face_references)
        if outcome == "missing":
            return FaceDeletionResult((), ())
        if outcome == "duplicate":
            return FaceDeletionResult(payload.provider_face_references * 2, ())
        if outcome == "unavailable":
            raise MyPhotosUnavailable("SYNTHETIC_PROVIDER_BUSY", "Synthetic busy provider")
        if outcome == "unexpected":
            raise RuntimeError("synthetic private provider detail")
        return await original_delete(payload)

    monkeypatch.setattr(provider, "delete_faces", delete_faces)
    if outcome == "not_configured":
        monkeypatch.setattr(provider, "ready", False)
    locator = GalleryManifestLocator(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity=request.manifest_identity,
    )
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    if outcome != "valid":
        with pytest.raises(MyPhotosUnavailable) as captured:
            await service.cancel_manifest(
                actor=actor,
                mfa_verified_at=datetime.now(UTC),
                locator=locator,
            )
        assert "synthetic private provider detail" not in str(captured.value)
        async with sessions() as session:
            face = await session.get(MyPhotoFaceOccurrenceModel, face_id)
            assert face.active and face.deleted_at is None
            assert await session.get(MyPhotoMediaAssetModel, asset_id) is not None
        monkeypatch.setattr(provider, "ready", True)
        monkeypatch.setattr(provider, "delete_faces", original_delete)
    pending = await service.cancel_manifest(
        actor=actor,
        mfa_verified_at=datetime.now(UTC),
        locator=locator,
    )
    assert pending.cancellation_requested
    async with sessions() as session:
        face = await session.get(MyPhotoFaceOccurrenceModel, face_id)
        assert not face.active and face.deleted_at is not None
    complete = await service.cancel_manifest(
        actor=actor,
        mfa_verified_at=datetime.now(UTC),
        locator=locator,
    )
    assert complete.state == "cancelled"
    async with sessions() as session:
        assert await session.scalar(select(func.count(MyPhotoFaceOccurrenceModel.id))) == 0
        assert await session.get(MyPhotoMediaAssetModel, asset_id) is None
