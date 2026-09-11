"""Exercise locked mutations with a real superadmin using a lower access level."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import revalidate_access_level_actor
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, UserModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.document_distribution_scope import _lock_active_document_scope
from app.presentation.api.v1.routes.document_rename import _lock_active_rename_actor
from app.presentation.api.v1.routes.passport_routes.bulk_actions import (
    _lock_active_bulk_approval_actor,
)
from app.presentation.api.v1.routes.passport_routes.excel_import import (
    _lock_and_reauthorize_passport_excel_import,
)
from app.presentation.api.v1.routes.whatsapp_scope import _lock_active_whatsapp_actor


async def _seed(session: AsyncSession, role: UserRole, *, owned: bool = True):
    agency_id, user_id, group_id = (uuid.uuid4() for _ in range(3))
    session.add(AgencyModel(id=agency_id, name="Preview agency", email="agency@example.test"))
    session.add(UserModel(
        id=user_id, email="owner@example.test", full_name="Owner", hashed_password="unused",
        role=UserRole.SUPER_ADMIN.value, agency_id=None,
    ))
    await session.flush()
    session.add(ClientGroupModel(
        id=group_id, agency_id=agency_id, name="Preview group", token=str(uuid.uuid4()),
        status="active", created_by_user_id=user_id if owned else None,
    ))
    await session.commit()
    actual = await UserRepository(session).get_by_id(user_id)
    assert actual is not None
    return replace(
        actual, role=role, agency_id=agency_id, actual_role=UserRole.SUPER_ADMIN,
        actual_agency_id=None, access_level_agency_name="Preview agency",
    ), group_id


@pytest.mark.parametrize("role", [UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF])
@pytest.mark.parametrize("workflow", ["approval", "whatsapp", "distribution", "rename", "excel"])
async def test_locked_mutation_retains_selected_level_and_real_identity(
    db_session: AsyncSession, role: UserRole, workflow: str,
) -> None:
    user, group_id = await _seed(db_session, role)
    assert user.agency_id is not None
    if workflow == "approval":
        actor = await _lock_active_bulk_approval_actor(db_session, user)
    elif workflow == "whatsapp":
        actor = await _lock_active_whatsapp_actor(
            db_session, current_user=user, require_agency=True,
        )
    elif workflow == "distribution":
        actor, _ = await _lock_active_document_scope(
            db_session, current_user=user, agency_id=user.agency_id, group_id=group_id,
        )
    elif workflow == "rename":
        actor = await _lock_active_rename_actor(
            db_session, user_id=user.id, agency_id=user.agency_id,
            expected_role=user.role, current_user=user,
        )
    else:
        actor, _ = await _lock_and_reauthorize_passport_excel_import(
            db_session, group_id=group_id, expected_agency_id=user.agency_id,
            user_id=user.id, current_user=user,
        )
    assert actor.id == user.id
    assert actor.role == role
    assert actor.agency_id == user.agency_id
    stored = (await db_session.execute(select(UserModel))).scalar_one()
    assert stored.role == UserRole.SUPER_ADMIN.value
    assert stored.agency_id is None


@pytest.mark.parametrize("workflow", ["distribution", "excel"])
async def test_reloading_superadmin_does_not_bypass_staff_group_scope(
    db_session: AsyncSession, workflow: str,
) -> None:
    user, group_id = await _seed(db_session, UserRole.AGENCY_STAFF, owned=False)
    assert user.agency_id is not None
    with pytest.raises(HTTPException) as caught:
        if workflow == "distribution":
            await _lock_active_document_scope(
                db_session, current_user=user, agency_id=user.agency_id, group_id=group_id,
            )
        else:
            await _lock_and_reauthorize_passport_excel_import(
                db_session, group_id=group_id, expected_agency_id=user.agency_id,
                user_id=user.id, current_user=user,
            )
    assert caught.value.status_code == 403


@pytest.mark.parametrize("change", ["role", "agency_id", "is_active", "session_version", "credential_state"])
def test_actor_refresh_rejects_changed_real_identity(change: str) -> None:
    actual = User(uuid.uuid4(), "owner@example.test", "unused", "Owner", UserRole.SUPER_ADMIN, None)
    view = replace(
        actual, role=UserRole.AGENCY_MANAGER, agency_id=uuid.uuid4(),
        actual_role=UserRole.SUPER_ADMIN, actual_agency_id=None,
    )
    value = {
        "role": UserRole.AGENCY_STAFF,
        "agency_id": uuid.uuid4(),
        "is_active": False,
        "session_version": 2,
        "credential_state": "invited",
    }[change]
    with pytest.raises(AuthorizationError):
        revalidate_access_level_actor(view, replace(actual, **{change: value}))
