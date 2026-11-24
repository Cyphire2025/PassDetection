"""Current persisted authority must still hold after external image work."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.entities.entities import UserRole
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    PassportImageCropModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import passport_image_library as route
from app.presentation.api.v1.schemas.passport_schemas import PassportVisaAiImageUseRequest
from tests.route_dependencies import set_route_dependency
from tests.unit.presentation.test_passport_image_library_commit_outcomes import ImageStorage


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["manual", "select"])
@pytest.mark.parametrize(
    "change",
    [
        "unchanged",
        "profile",
        "deactivate",
        "role",
        "agency",
        "session",
        "agency-inactive",
        "group-deleted",
        "staff-assigned",
        "staff-revoked",
        "super-retained",
        "borrowed-profile",
        "source-changed",
    ],
)
async def test_current_authority_is_rechecked_after_image_storage_work(
    db_session, monkeypatch, operation, change
):
    agency = AgencyModel(id=uuid.uuid4(), name="Authority", email="authority@example.test")
    other = AgencyModel(id=uuid.uuid4(), name="Other", email="other-authority@example.test")
    db_session.add_all([agency, other])
    await db_session.flush()
    is_super = change in {"super-retained", "borrowed-profile"}
    is_staff = change.startswith("staff-")
    user = UserModel(
        id=uuid.uuid4(),
        agency_id=None if is_super else agency.id,
        email="authority-user@example.test",
        full_name="Authority User",
        hashed_password="synthetic",
        role="super_admin" if is_super else "agency_staff" if is_staff else "agency_admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    state = UserSecurityStateModel(user_id=user.id, credential_state="active", session_version=1)
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        created_by_user_id=None if is_staff else user.id,
        name="Authority Group",
        token=uuid.uuid4().hex,
        travel_date=datetime.now(UTC).date() + timedelta(days=20),
    )
    db_session.add_all([state, group])
    await db_session.flush()
    if is_staff:
        db_session.add(
            ManagerGroupAccessModel(
                id=uuid.uuid4(),
                manager_id=user.id,
                group_id=group.id,
                agency_id=agency.id,
            )
        )
    if change == "super-retained":
        agency.is_active = False
        group.deleted_at = datetime.now(UTC)
    submission = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        group_id=group.id,
        client_name="Synthetic Passenger",
        image_s3_key="front/authority.jpg",
        passport_back_cover_s3_key="back/authority.jpg",
        status="staff_approved",
    )
    db_session.add(submission)
    await db_session.flush()
    source = submission.passport_back_cover_s3_key
    image_type = PassportImageType.PASSPORT_BACK_COVER
    item = await PassportImageLibraryRepository(db_session).create_manual(
        submission_id=submission.id,
        image_type=image_type,
        storage_key=f"passport-image-library/{agency.id}/{submission.id}/existing.jpg",
        original_source_storage_key=source,
        content_sha256="a" * 64,
        created_by_user_id=user.id,
    )
    await db_session.commit()
    agency_id, other_agency_id, group_id, submission_id, item_id = (
        agency.id,
        other.id,
        group.id,
        submission.id,
        item.id,
    )
    actor = await UserRepository(db_session).get_by_id(user.id)
    if change == "borrowed-profile":
        actor = replace(
            actor,
            role=UserRole.AGENCY_MANAGER,
            agency_id=agency_id,
            actual_role=UserRole.SUPER_ADMIN,
            actual_agency_id=None,
        )
    await db_session.rollback()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = ImageStorage({source: b"original", item.storage_key: b"existing"})
    original_keys = set(storage.objects)
    write = storage.upload_file
    observed_change = False

    async def upload(content, key, content_type):
        nonlocal observed_change
        await write(content, key, content_type)
        if not key.startswith("passport-crops/"):
            return key
        async with factory() as editor:
            if change in {"profile", "borrowed-profile"}:
                await editor.execute(
                    update(UserModel)
                    .where(UserModel.id == actor.id)
                    .values(full_name="Renewed Profile", email="renewed-authority@example.test")
                )
            elif change == "deactivate":
                await editor.execute(
                    update(UserModel).where(UserModel.id == actor.id).values(is_active=False)
                )
            elif change == "role":
                await editor.execute(
                    update(UserModel)
                    .where(UserModel.id == actor.id)
                    .values(role="agency_coordinator")
                )
            elif change == "agency":
                await editor.execute(
                    update(UserModel)
                    .where(UserModel.id == actor.id)
                    .values(agency_id=other_agency_id)
                )
            elif change == "session":
                await editor.execute(
                    update(UserSecurityStateModel)
                    .where(UserSecurityStateModel.user_id == actor.id)
                    .values(session_version=2)
                )
            elif change == "agency-inactive":
                await editor.execute(
                    update(AgencyModel).where(AgencyModel.id == agency_id).values(is_active=False)
                )
            elif change == "group-deleted":
                await editor.execute(
                    update(ClientGroupModel)
                    .where(ClientGroupModel.id == group_id)
                    .values(deleted_at=datetime.now(UTC))
                )
            elif change == "staff-revoked":
                await editor.execute(
                    delete(ManagerGroupAccessModel).where(
                        ManagerGroupAccessModel.manager_id == actor.id,
                        ManagerGroupAccessModel.group_id == group_id,
                    )
                )
            elif change == "source-changed":
                storage.objects["back/replacement.jpg"] = b"another-request"
                original_keys.add("back/replacement.jpg")
                await editor.execute(
                    update(PassportSubmissionModel)
                    .where(
                        PassportSubmissionModel.id == submission_id,
                    )
                    .values(passport_back_cover_s3_key="back/replacement.jpg")
                )
            await editor.commit()
        observed_change = True
        return key

    storage.upload_file = upload
    set_route_dependency(monkeypatch, route, "MinioStorageRepository", lambda: storage)
    set_route_dependency(
        monkeypatch,
        route,
        "_validated_upload_file",
        AsyncMock(return_value=SimpleNamespace(content=b"upload", content_type="image/jpeg")),
    )
    set_route_dependency(
        monkeypatch,
        route,
        "render_passport_image_crop",
        lambda *_args, **_kwargs: SimpleNamespace(
            content=b"derivative",
            content_type="image/jpeg",
            extension=".jpg",
            source_width=900,
            source_height=600,
        ),
    )
    # Both policy checks and the successful persisted audit use the real
    # repositories. External storage remains the isolated adapter above.

    async def execute():
        if operation == "manual":
            return await route.upload_passport_image_library_item(
                submission_id=submission_id,
                image_type=image_type,
                background_tasks=BackgroundTasks(),
                image=SimpleNamespace(),
                expected_revision=0,
                _csrf=None,
                current_user=actor,
                session=db_session,
            )
        return await route.use_passport_image_library_item(
            submission_id=submission_id,
            image_type=image_type,
            item_id=item_id,
            body=PassportVisaAiImageUseRequest(x=0, y=0, width=1, height=1, expected_revision=0),
            background_tasks=BackgroundTasks(),
            _csrf=None,
            current_user=actor,
            session=db_session,
        )

    permitted = change in {
        "unchanged",
        "profile",
        "staff-assigned",
        "super-retained",
        "borrowed-profile",
    }
    if permitted:
        await execute()
    else:
        with pytest.raises(HTTPException) as denied:
            await execute()
        assert denied.value.status_code == (409 if change == "source-changed" else 403)
    assert observed_change
    async with factory() as observer:
        crops = await observer.scalar(
            select(func.count())
            .select_from(PassportImageCropModel)
            .where(PassportImageCropModel.submission_id == submission_id)
        )
        assert crops == int(permitted)
        reads = list(
            (
                await observer.scalars(
                    select(AuditLogModel).where(
                        AuditLogModel.entity_id == str(submission_id),
                        AuditLogModel.action == "sensitive_read.authorized",
                    )
                )
            ).all()
        )
        assert len(reads) == int(permitted)
    if not permitted:
        assert set(storage.objects) == original_keys
