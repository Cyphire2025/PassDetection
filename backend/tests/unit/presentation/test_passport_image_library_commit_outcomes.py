"""Real persisted image references must survive an uncertain commit response."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
    passport_image_storage_key,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportImageCropModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.passport_image_library_model import PassportImageLibraryItemModel
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import passport_image_library as route
from app.presentation.api.v1.schemas.passport_schemas import PassportVisaAiImageUseRequest
from tests.route_dependencies import set_route_dependency


class ImageStorage:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.deleted = []

    async def upload_file(self, content, key, _content_type):
        self.objects[key] = content
        return key

    async def get_file(self, key):
        return self.objects[key]

    async def delete_files(self, keys):
        self.deleted.extend(keys)
        for key in keys:
            self.objects.pop(key, None)
        return len(keys)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["manual", "select"])
@pytest.mark.parametrize(
    "image_type", [PassportImageType.PASSPORT_FRONT, PassportImageType.PASSPORT_BACK_COVER]
)
@pytest.mark.parametrize("lost_ack", [False, True], ids=["ordinary", "lost-ack"])
async def test_committed_library_and_crop_objects_survive_lost_acknowledgement(
    db_session,
    monkeypatch,
    operation,
    image_type,
    lost_ack,
):
    agency = AgencyModel(id=uuid.uuid4(), name="Image fixture", email="image-agency@example.test")
    db_session.add(agency)
    await db_session.flush()
    user = UserModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        email="image-admin@example.test",
        full_name="Image Admin",
        hashed_password="synthetic-hash",
        role="agency_admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        created_by_user_id=user.id,
        name="Image Group",
        token=uuid.uuid4().hex,
        travel_date=datetime.now(UTC).date() + timedelta(days=20),
    )
    db_session.add(group)
    await db_session.flush()
    submission = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        group_id=group.id,
        client_name="Synthetic Passenger",
        image_s3_key="front/synthetic-front.jpg",
        passport_back_cover_s3_key="back/synthetic-cover.jpg",
        status="staff_approved",
    )
    db_session.add(submission)
    await db_session.commit()
    actor = await UserRepository(db_session).get_by_id(user.id)
    value = await PassportSubmissionRepository(db_session).get_by_id(submission.id)
    source = passport_image_storage_key(value, image_type)
    storage = ImageStorage({source: b"canonical-source"})
    item = None
    if operation == "select":
        key = f"passport-image-library/{agency.id}/{submission.id}/{image_type.value}/manual/existing.jpg"
        item = await PassportImageLibraryRepository(db_session).create_manual(
            submission_id=submission.id,
            image_type=image_type,
            storage_key=key,
            original_source_storage_key=source,
            content_sha256="a" * 64,
            created_by_user_id=user.id,
        )
        storage.objects[key] = b"canonical-existing"
    await db_session.commit()
    set_route_dependency(
        monkeypatch,
        route,
        "_resolve_authorized_staff_passport_image",
        AsyncMock(return_value=(value, source)),
    )
    set_route_dependency(monkeypatch, route, "MinioStorageRepository", lambda: storage)
    set_route_dependency(
        monkeypatch,
        route,
        "_validated_upload_file",
        AsyncMock(
            return_value=SimpleNamespace(content=b"canonical-upload", content_type="image/jpeg")
        ),
    )
    set_route_dependency(
        monkeypatch,
        route,
        "render_passport_image_crop",
        lambda *_args, **_kwargs: SimpleNamespace(
            content=b"canonical-derivative",
            content_type="image/jpeg",
            extension=".jpg",
            source_width=900,
            source_height=600,
        ),
    )
    set_route_dependency(monkeypatch, route, "propagate_mobile_passenger_change", AsyncMock())
    real_commit = db_session.commit

    async def dispatch(result, *, session, background_tasks):
        await session.commit()

    set_route_dependency(monkeypatch, route, "_dispatch_processing_job", dispatch)

    async def commit():
        await real_commit()
        if lost_ack:
            raise ConnectionError("Synthetic commit acknowledgement lost after persistence")

    monkeypatch.setattr(db_session, "commit", commit)

    async def execute():
        if operation == "manual":
            return await route.upload_passport_image_library_item(
                submission_id=submission.id,
                image_type=image_type,
                background_tasks=BackgroundTasks(),
                image=SimpleNamespace(),
                expected_revision=0,
                _csrf=None,
                current_user=actor,
                session=db_session,
            )
        return await route.use_passport_image_library_item(
            submission_id=submission.id,
            image_type=image_type,
            item_id=item.id,
            body=PassportVisaAiImageUseRequest(x=0, y=0, width=1, height=1, expected_revision=0),
            background_tasks=BackgroundTasks(),
            _csrf=None,
            current_user=actor,
            session=db_session,
        )

    if lost_ack:
        with pytest.raises(ConnectionError):
            await execute()
    else:
        await execute()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as observer:
        crop = (
            await observer.scalars(
                select(PassportImageCropModel).where(
                    PassportImageCropModel.submission_id == submission.id,
                    PassportImageCropModel.image_type == image_type.value,
                )
            )
        ).one()
        library = list(
            (
                await observer.scalars(
                    select(PassportImageLibraryItemModel).where(
                        PassportImageLibraryItemModel.submission_id == submission.id,
                    )
                )
            ).all()
        )
        references = {
            crop.source_storage_key,
            crop.derived_storage_key,
            *[entry.storage_key for entry in library],
        }
        if crop.edit_source_storage_key:
            references.add(crop.edit_source_storage_key)
        assert references <= storage.objects.keys(), (
            "Committed passport image references lost their stored bytes"
        )
        assert not references.intersection(storage.deleted)
