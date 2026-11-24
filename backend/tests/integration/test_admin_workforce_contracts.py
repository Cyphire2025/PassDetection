"""Persisted invitation secrecy and workforce access behavior through the stable facade."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.identity_security_models import IdentityActionTokenModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.presentation.api.v1.routes import admin, admin_workforce
from app.presentation.api.v1.schemas.operations_schemas import (
    AssignManagerGroupsRequest,
    CreateManagerRequest,
)
from tests.persistence import persist_graph


async def _actor(session: AsyncSession, role: UserRole = UserRole.AGENCY_ADMIN) -> User:
    agency_id, user_id = uuid.uuid4(), uuid.uuid4()
    await persist_graph(
        session,
        [
            AgencyModel(id=agency_id, name="Synthetic workforce", email=f"{agency_id}@example.com"),
            UserModel(
                id=user_id,
                email="owner@example.com",
                full_name="Synthetic owner",
                hashed_password="fixture-hash",
                agency_id=agency_id,
                role=role.value,
            ),
        ],
    )
    return User(
        id=user_id,
        email="owner@example.com",
        full_name="Synthetic owner",
        hashed_password="fixture-hash",
        agency_id=agency_id,
        role=role,
    )


def _request() -> Request:
    return Request({"type": "http", "headers": [], "client": ("127.0.0.1", 12345)})


@pytest.mark.parametrize("role", [UserRole.AGENCY_ADMIN, UserRole.SUPER_ADMIN])
async def test_manager_invitation_stores_only_single_use_hash_and_returns_private_response(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    role: UserRole,
) -> None:
    actor = await _actor(db_session, role)
    monkeypatch.setattr(admin_workforce, "hash_password", lambda _value: "synthetic-password-hash")
    response = Response()
    before = datetime.now(UTC)
    invited = await admin.create_manager(
        body=CreateManagerRequest(full_name="  Invited Manager  ", email="NEW@example.com"),
        request=_request(),
        response=response,
        current_user=actor,
        session=db_session,
    )
    await db_session.flush()

    account = await db_session.get(UserModel, invited.id)
    state = await db_session.get(UserSecurityStateModel, invited.id)
    token = (
        await db_session.scalars(
            select(IdentityActionTokenModel).where(
                IdentityActionTokenModel.user_id == invited.id,
            )
        )
    ).one()
    audit = (
        await db_session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.action == "manager.invited",
            )
        )
    ).one()
    assert account is not None and state is not None
    assert account.email == invited.email == "new@example.com"
    assert account.full_name == invited.full_name == "Invited Manager"
    assert account.agency_id == actor.agency_id and account.role == "agency_manager"
    assert state.credential_state == invited.credential_state == "invited"
    assert state.mfa_required is True and state.session_version == 1
    assert invited.activation_token and token.token_hash != invited.activation_token
    assert len(token.token_hash) == 64 and token.purpose == "activation"
    assert token.created_by_user_id == actor.id
    assert (
        before + timedelta(days=7)
        <= token.expires_at.replace(tzinfo=UTC)
        <= datetime.now(UTC) + timedelta(days=7)
    )
    assert (
        await IdentitySecurityRepository(db_session).get_valid_action_token(
            raw_token=invited.activation_token,
            purpose="activation",
        )
        is token
    )
    assert invited.activation_token not in json.dumps(audit.metadata_json)
    assert "hashed_password" not in invited.model_dump()
    assert "private" in response.headers["cache-control"]
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["pragma"] == "no-cache"
    listed = await admin.list_managers(current_user=actor, session=db_session)
    assert len(listed) == 1 and listed[0].id == invited.id
    assert listed[0].credential_state == "invited" and listed[0].activation_token is None


@pytest.mark.parametrize("reason,status_code", [("no_agency", 400), ("duplicate_email", 409)])
async def test_rejected_invitation_creates_no_account_token_or_audit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    status_code: int,
) -> None:
    actor = await _actor(db_session)
    if reason == "no_agency":
        actor.agency_id = None

    def unexpected_password(_value: str) -> str:
        raise AssertionError("Rejected invitation attempted credential generation")

    monkeypatch.setattr(admin_workforce, "hash_password", unexpected_password)
    with pytest.raises(HTTPException) as denied:
        await admin.create_manager(
            body=CreateManagerRequest(full_name="Synthetic duplicate", email="OWNER@example.com"),
            request=_request(),
            response=Response(),
            current_user=actor,
            session=db_session,
        )
    assert denied.value.status_code == status_code
    assert await db_session.scalar(select(func.count()).select_from(UserModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(IdentityActionTokenModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AuditLogModel)) == 0


@pytest.mark.parametrize("target_role", [UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF])
@pytest.mark.parametrize("credential_state", [None, "invited"])
async def test_assignment_keeps_implicit_ownership_and_only_persists_extra_access(
    db_session: AsyncSession,
    target_role: UserRole,
    credential_state: str | None,
) -> None:
    actor = await _actor(db_session)
    target_id, created_id, assigned_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await persist_graph(
        db_session,
        [
            UserModel(
                id=target_id,
                email="member@example.com",
                full_name="Synthetic member",
                hashed_password="fixture-hash",
                agency_id=actor.agency_id,
                role=target_role.value,
            ),
            ClientGroupModel(
                id=created_id,
                name="Owned",
                token=uuid.uuid4().hex,
                agency_id=actor.agency_id,
                created_by_user_id=target_id,
            ),
            ClientGroupModel(
                id=assigned_id,
                name="Assigned",
                token=uuid.uuid4().hex,
                agency_id=actor.agency_id,
                created_by_user_id=actor.id,
            ),
        ],
    )
    if credential_state is not None:
        db_session.add(UserSecurityStateModel(user_id=target_id, credential_state=credential_state))
        await db_session.flush()
    body = AssignManagerGroupsRequest(group_ids=[created_id, assigned_id, assigned_id])
    if target_role == UserRole.AGENCY_MANAGER:
        result = await admin.assign_manager_groups(target_id, body, actor, db_session)
    else:
        result = await admin.assign_staff_groups(target_id, body, actor, db_session)
    assert result.id == target_id and result.credential_state == (credential_state or "active")
    assert [row.id for row in result.created_groups] == [created_id]
    assert [row.id for row in result.assigned_groups] == [assigned_id]
    access = (await db_session.scalars(select(ManagerGroupAccessModel))).all()
    assert len(access) == 1 and access[0].group_id == assigned_id
    assert access[0].manager_id == target_id and access[0].agency_id == actor.agency_id
    available = await admin.list_admin_groups(current_user=actor, session=db_session)
    assert {group.id for group in available} == {created_id, assigned_id}
    if target_role == UserRole.AGENCY_STAFF:
        staff = await admin.list_staff_for_access(current_user=actor, session=db_session)
        assert len(staff) == 1 and staff[0] == result

    # Replacing explicit assignments leaves ownership-derived access intact.
    empty = AssignManagerGroupsRequest(group_ids=[])
    if target_role == UserRole.AGENCY_MANAGER:
        result = await admin.assign_manager_groups(target_id, empty, actor, db_session)
    else:
        result = await admin.assign_staff_groups(target_id, empty, actor, db_session)
    assert [row.id for row in result.created_groups] == [created_id]
    assert result.assigned_groups == []
    assert await db_session.scalar(select(func.count()).select_from(ManagerGroupAccessModel)) == 0
