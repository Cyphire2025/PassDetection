"""Persisted management policy boundaries and account-list tenant selection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import AgencyModel, UserModel
from app.presentation.api.v1.routes import admin_accounts
from tests.integration.test_admin_workforce_contracts import _actor
from tests.persistence import persist_graph

CALLERS = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]
SUBJECTS = [UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR]
OWN_AGENCY_POLICY = {
    UserRole.SUPER_ADMIN: set(SUBJECTS),
    UserRole.AGENCY_ADMIN: set(SUBJECTS),
    UserRole.AGENCY_MANAGER: {UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR},
}


@pytest.mark.parametrize("actor_role", CALLERS)
@pytest.mark.parametrize("subject_role", SUBJECTS)
@pytest.mark.parametrize("foreign_agency", [False, True])
async def test_manageable_account_matches_existing_role_and_tenant_policy(
    db_session: AsyncSession,
    actor_role: UserRole,
    subject_role: UserRole,
    foreign_agency: bool,
) -> None:
    actor = await _actor(db_session, actor_role)
    agency_id = uuid.uuid4() if foreign_agency else actor.agency_id
    rows = []
    if foreign_agency:
        rows.append(AgencyModel(id=agency_id, name="Synthetic other", email="other@example.com"))
    subject = UserModel(
        id=uuid.uuid4(),
        email="subject@example.com",
        full_name="Synthetic subject",
        hashed_password="fixture-hash",
        agency_id=agency_id,
        role=subject_role.value,
    )
    await persist_graph(db_session, [*rows, subject])
    allowed = subject_role in OWN_AGENCY_POLICY[actor_role]
    if foreign_agency and actor_role != UserRole.SUPER_ADMIN:
        allowed = False
    if not allowed:
        with pytest.raises(HTTPException) as denied:
            await admin_accounts._get_manageable_account(db_session, actor, subject.id)
        assert denied.value.status_code == 403
    else:
        found, agency_name = await admin_accounts._get_manageable_account(
            db_session, actor, subject.id
        )
        assert found is subject and agency_name


async def test_manager_can_manage_own_account_without_granting_other_manager_access(
    db_session: AsyncSession,
) -> None:
    actor = await _actor(db_session, UserRole.AGENCY_MANAGER)
    found, _ = await admin_accounts._get_manageable_account(db_session, actor, actor.id)
    assert found.id == actor.id


@pytest.mark.parametrize("reason", ["missing", "deleted", "unmanaged_role"])
async def test_unavailable_subjects_are_filtered_before_management_projection(
    db_session: AsyncSession,
    reason: str,
) -> None:
    actor = await _actor(db_session, UserRole.SUPER_ADMIN)
    subject_id = uuid.uuid4()
    if reason != "missing":
        await persist_graph(
            db_session,
            [
                UserModel(
                    id=subject_id,
                    email="unavailable@example.com",
                    full_name="Synthetic unavailable",
                    hashed_password="fixture-hash",
                    agency_id=actor.agency_id,
                    role=UserRole.AGENCY_ADMIN.value
                    if reason == "unmanaged_role"
                    else UserRole.AGENCY_STAFF.value,
                    deleted_at=datetime.now(UTC) if reason == "deleted" else None,
                )
            ],
        )
    with pytest.raises(HTTPException) as unavailable:
        await admin_accounts._get_manageable_account(db_session, actor, subject_id)
    assert unavailable.value.status_code == 404


@pytest.mark.parametrize("actor_role", CALLERS)
async def test_account_lists_keep_scope_deleted_filters_and_private_credentials(
    db_session: AsyncSession,
    actor_role: UserRole,
) -> None:
    actor = await _actor(db_session, actor_role)
    foreign_id = uuid.uuid4()
    own = {role: uuid.uuid4() for role in SUBJECTS}
    foreign = {role: uuid.uuid4() for role in SUBJECTS}
    unassigned_staff, removed_staff = uuid.uuid4(), uuid.uuid4()
    accounts = [
        UserModel(
            id=identities[role],
            email=f"{identities[role]}@example.com",
            full_name="Synthetic listed",
            hashed_password="fixture-hash",
            agency_id=agency_id,
            role=role.value,
        )
        for agency_id, identities in [(actor.agency_id, own), (foreign_id, foreign)]
        for role in SUBJECTS
    ]
    accounts.extend(
        [
            UserModel(
                id=unassigned_staff,
                email="unassigned@example.com",
                full_name="Unassigned",
                hashed_password="fixture-hash",
                agency_id=None,
                role=UserRole.AGENCY_STAFF.value,
            ),
            UserModel(
                id=removed_staff,
                email="removed@example.com",
                full_name="Removed",
                hashed_password="fixture-hash",
                agency_id=actor.agency_id,
                role=UserRole.AGENCY_STAFF.value,
                deleted_at=datetime.now(UTC),
            ),
        ]
    )
    await persist_graph(
        db_session,
        [
            AgencyModel(id=foreign_id, name="Synthetic other", email="other@example.com"),
            *accounts,
        ],
    )
    managed_ids = {own[UserRole.AGENCY_COORDINATOR]}
    staff_ids = {own[UserRole.AGENCY_STAFF]}
    if actor_role != UserRole.AGENCY_MANAGER:
        managed_ids |= staff_ids
    if actor_role == UserRole.SUPER_ADMIN:
        managed_ids |= {
            foreign[UserRole.AGENCY_STAFF],
            foreign[UserRole.AGENCY_COORDINATOR],
            unassigned_staff,
        }
        staff_ids |= {foreign[UserRole.AGENCY_STAFF], unassigned_staff}
    managed = await admin_accounts.list_managed_accounts(current_user=actor, session=db_session)
    staff = await admin_accounts.list_staff_accounts(current_user=actor, session=db_session)
    assert {row.id for row in managed} == managed_ids
    assert {row.id for row in staff} == staff_ids
    assert all(row.activation_token is None for row in [*managed, *staff])
