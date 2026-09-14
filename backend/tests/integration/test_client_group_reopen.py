from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.platform_policies import PlatformPolicies
from app.application.use_cases.client_groups.get_client_group_by_token_use_case import (
    GetClientGroupByTokenUseCase,
)
from app.application.use_cases.client_groups.restore_client_group_use_case import (
    RestoreClientGroupUseCase,
)
from app.application.use_cases.client_groups.revoke_client_group_use_case import (
    RevokeClientGroupUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import ClientGroup, GroupStatus, User, UserRole
from app.domain.exceptions.exceptions import EntityNotFoundError, GroupClosedError, ValidationError
from app.infrastructure.database.models import AgencyModel, PassportSubmissionModel, UserModel
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.routes.client_groups import restore_client_group, revoke_client_group


async def _seed_group(session: AsyncSession) -> tuple[User, ClientGroup]:
    user = User.create(
        email="manager@example.test",
        hashed_password="test-hash",
        full_name="Group Manager",
        role=UserRole.AGENCY_MANAGER,
        agency_id=uuid.uuid4(),
    )
    session.add_all(
        [
            AgencyModel(id=user.agency_id, name="Test Agency", email="agency@example.test"),
            UserModel(
                id=user.id,
                email=user.email,
                hashed_password=user.hashed_password,
                full_name=user.full_name,
                role=user.role.value,
                agency_id=user.agency_id,
            ),
        ]
    )
    await session.flush()
    group = ClientGroup.create(
        name="Reopenable Group",
        token="same-public-group-token",
        agency_id=user.agency_id,
        created_by_user_id=user.id,
        destination="Vietnam",
        departure_cities=["Delhi", "Mumbai"],
        require_selfie=True,
        staff_code_enabled=True,
        notes="Keep the existing trip settings",
    )
    await ClientGroupRepository(session).save(group)
    return user, group


@pytest.mark.asyncio
async def test_closed_group_reopens_same_link_and_resumes_configured_uploads(
    db_session: AsyncSession,
) -> None:
    user, group = await _seed_group(db_session)
    previous_submission = PassportSubmissionModel(
        id=uuid.uuid4(),
        group_id=group.id,
        agency_id=group.agency_id,
        client_name="Existing Passenger",
        image_s3_key="existing-passport.jpg",
    )
    db_session.add(previous_submission)
    await db_session.flush()
    group_repo = ClientGroupRepository(db_session)
    policy_provider = AsyncMock()
    policy_provider.load.return_value = PlatformPolicies(passport_data_retention_days=30)
    lookup = GetClientGroupByTokenUseCase(group_repo)
    original = await lookup.execute(group.token)
    passport_repo = AsyncMock()
    passport_repo.save_idempotent.side_effect = lambda submission: (submission, True)
    storage_repo = AsyncMock()
    upload = SubmitPassportUseCase(group_repo, passport_repo, storage_repo)
    upload_args = dict(
        token=group.token,
        file_content=b"front",
        content_type="image/jpeg",
        filename="front.jpg",
        client_name="New Passenger",
        passport_back=(b"back", "image/jpeg", "back.jpg"),
    )

    await revoke_client_group(
        link_id=group.id,
        current_user=user,
        use_case=RevokeClientGroupUseCase(group_repo, policy_provider),
        session=db_session,
    )
    closed = await group_repo.get_by_id(group.id)
    assert closed is not None
    assert closed.status == GroupStatus.CLOSED
    assert closed.closed_at is not None
    assert closed.passport_purge_at is not None
    assert closed.passport_retention_days_applied == 30
    with pytest.raises(GroupClosedError):
        await lookup.execute(group.token)
    with pytest.raises(EntityNotFoundError):
        await upload.execute(**upload_args)
    storage_repo.upload_file.assert_not_awaited()

    response = await restore_client_group(
        link_id=group.id,
        current_user=user,
        use_case=RestoreClientGroupUseCase(group_repo),
        session=db_session,
    )
    reopened = await group_repo.get_by_token(group.token)
    assert response.status == "active"
    assert reopened is not None
    assert reopened.id == group.id
    assert reopened.closed_at is None
    assert reopened.deleted_at is None
    assert reopened.passport_purge_at is None
    assert reopened.passport_retention_days_applied is None
    assert await lookup.execute(group.token) == original
    assert await db_session.get(PassportSubmissionModel, previous_submission.id) is not None

    with pytest.raises(ValidationError) as missing_selfie:
        await upload.execute(**upload_args)
    assert missing_selfie.value.field == "passport_photo_file"
    storage_repo.upload_file.assert_not_awaited()
    submitted = await upload.execute(
        **upload_args,
        passport_photo=(b"selfie", "image/jpeg", "selfie.jpg"),
    )
    assert submitted.group_id == group.id
    assert submitted.passport_photo_s3_key is not None
    assert storage_repo.upload_file.await_count == 3
    passport_repo.save_idempotent.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["other_agency", "coordinator", "unassigned_staff"])
async def test_open_respects_existing_group_management_permissions(
    db_session: AsyncSession,
    actor: str,
) -> None:
    user, group = await _seed_group(db_session)
    group.close(passport_retention_days=30)
    group_repo = ClientGroupRepository(db_session)
    await group_repo.update(group)
    if actor == "other_agency":
        user.agency_id = uuid.uuid4()
    elif actor == "coordinator":
        user.role = UserRole.AGENCY_COORDINATOR
    else:
        user.id = uuid.uuid4()
        user.role = UserRole.AGENCY_STAFF

    with pytest.raises(HTTPException) as forbidden:
        await restore_client_group(
            link_id=group.id,
            current_user=user,
            use_case=RestoreClientGroupUseCase(group_repo),
            session=db_session,
        )

    assert forbidden.value.status_code == 403
    unchanged = await group_repo.get_by_id(group.id)
    assert unchanged is not None
    assert unchanged.status == GroupStatus.CLOSED
    assert unchanged.closed_at is not None
    assert unchanged.passport_purge_at is not None
