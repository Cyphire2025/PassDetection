"""Exercise submission-delete roles through HTTP and real isolated persistence."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.destructive_mutation_policy import DestructiveMutationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    NotificationModel,
    PassportSubmissionModel,
    StorageCleanupJobModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.passport_routes import bulk_actions
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.middleware.error_handler import register_exception_handlers


@dataclass
class DeleteCase:
    session: AsyncSession
    actor: User
    group_id: uuid.UUID
    foreign_group_id: uuid.UUID
    own_ids: list[uuid.UUID]
    other_group_id: uuid.UUID
    other_submission_id: uuid.UUID
    foreign_submission_id: uuid.UUID

    @property
    def all_ids(self) -> set[uuid.UUID]:
        return {*self.own_ids, self.other_submission_id, self.foreign_submission_id}


@pytest.fixture
def external_effects(monkeypatch: pytest.MonkeyPatch):
    propagate = AsyncMock()
    cleanup = AsyncMock(return_value=None)
    monkeypatch.setattr(bulk_actions, "propagate_mobile_passenger_change", propagate)
    monkeypatch.setattr(bulk_actions, "process_storage_cleanup_job", cleanup)
    return propagate, cleanup


async def _seed(
    session: AsyncSession,
    *,
    role: UserRole = UserRole.AGENCY_MANAGER,
    access: str = "unowned",
    held: bool = False,
) -> DeleteCase:
    agency_id, foreign_agency_id, actor_id, owner_id = (uuid.uuid4() for _ in range(4))
    actor = User(
        actor_id,
        "reviewer@example.test",
        "unused",
        "Reviewer",
        role,
        None if role == UserRole.SUPER_ADMIN else agency_id,
    )
    session.add_all(
        [
            AgencyModel(id=agency_id, name="Agency", email="agency@example.test"),
            AgencyModel(id=foreign_agency_id, name="Other agency", email="other@example.test"),
            UserModel(
                id=actor_id,
                email=actor.email,
                full_name=actor.full_name,
                hashed_password="unused",
                role=role.value,
                agency_id=actor.agency_id,
            ),
            UserModel(
                id=owner_id,
                email="owner@example.test",
                full_name="Other group owner",
                hashed_password="unused",
                role=UserRole.AGENCY_ADMIN.value,
                agency_id=agency_id,
            ),
        ]
    )
    await session.flush()
    group_id, other_group_id, foreign_group_id = (uuid.uuid4() for _ in range(3))
    groups = [
        ClientGroupModel(
            id=group_id,
            agency_id=agency_id,
            name="Target group",
            token=str(uuid.uuid4()),
            status="active",
            created_by_user_id=actor_id if access == "owned" else owner_id,
            passport_legal_hold=held,
            passport_legal_hold_reason="Confidential legal review" if held else None,
            passport_legal_hold_set_at=datetime.now(tz=UTC) if held else None,
        ),
        ClientGroupModel(
            id=other_group_id,
            agency_id=agency_id,
            name="Other local group",
            token=str(uuid.uuid4()),
            status="active",
        ),
        ClientGroupModel(
            id=foreign_group_id,
            agency_id=foreign_agency_id,
            name="Foreign group",
            token=str(uuid.uuid4()),
            status="active",
        ),
    ]
    session.add_all(groups)
    await session.flush()
    if access == "assigned":
        session.add(
            ManagerGroupAccessModel(manager_id=actor_id, group_id=group_id, agency_id=agency_id)
        )
    own_ids = [uuid.uuid4() for _ in range(3)]
    other_submission_id, foreign_submission_id = uuid.uuid4(), uuid.uuid4()
    scopes = [(item, group_id, agency_id) for item in own_ids] + [
        (other_submission_id, other_group_id, agency_id),
        (foreign_submission_id, foreign_group_id, foreign_agency_id),
    ]
    for submission_id, parent_id, tenant_id in scopes:
        session.add(
            PassportSubmissionModel(
                id=submission_id,
                agency_id=tenant_id,
                group_id=parent_id,
                client_name="Test traveller",
                client_email="traveller@example.test",
                image_s3_key=f"front/{submission_id}.jpg",
                status="ai_approved",
            )
        )
        session.add(
            NotificationModel(
                agency_id=tenant_id,
                type="passport_ready",
                title="Passport ready",
                message="Synthetic notification",
                entity_type="passport_submission",
                entity_id=str(submission_id),
            )
        )
    await session.commit()
    return DeleteCase(
        session,
        actor,
        group_id,
        foreign_group_id,
        own_ids,
        other_group_id,
        other_submission_id,
        foreign_submission_id,
    )


@asynccontextmanager
async def _client(case: DeleteCase):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(bulk_actions.router, prefix="/api/v1/passports")

    async def database():
        try:
            yield case.session
            await case.session.commit()
        except Exception:
            await case.session.rollback()
            raise

    async def current_user(request: Request):
        request.state.auth_claims = {
            "amr": ["password", "totp"],
            "mfa_at": datetime.now(tz=UTC).timestamp(),
        }
        return case.actor

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_current_active_user] = current_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


async def _post(case: DeleteCase, ids: list[uuid.UUID], *, group_id: uuid.UUID | None = None):
    async with _client(case) as client:
        return await client.post(
            f"/api/v1/passports/groups/{group_id or case.group_id}/bulk-delete",
            json={"submission_ids": [str(item) for item in ids]},
        )


async def _audits(case: DeleteCase) -> dict[str, AuditLogModel]:
    rows = (await case.session.execute(select(AuditLogModel))).scalars().all()
    return {row.action: row for row in rows}


async def _assert_retained(case: DeleteCase, external_effects) -> None:
    remaining = set((await case.session.execute(select(PassportSubmissionModel.id))).scalars())
    assert remaining == case.all_ids
    notifications = set((await case.session.execute(select(NotificationModel.entity_id))).scalars())
    assert notifications == {str(item) for item in case.all_ids}
    assert set((await case.session.execute(select(ClientGroupModel.id))).scalars()) == {
        case.group_id,
        case.other_group_id,
        case.foreign_group_id,
    }
    assert not (await case.session.execute(select(StorageCleanupJobModel.id))).scalars().all()
    propagate, cleanup = external_effects
    propagate.assert_not_awaited()
    cleanup.assert_not_awaited()


@pytest.mark.parametrize(
    "role", [UserRole.AGENCY_MANAGER, UserRole.AGENCY_ADMIN, UserRole.SUPER_ADMIN]
)
@pytest.mark.parametrize("count", [1, 2])
async def test_manager_and_admins_delete_selected_submissions_with_real_audit_and_tombstones(
    db_session: AsyncSession, external_effects, role: UserRole, count: int
) -> None:
    case = await _seed(db_session, role=role)
    selected = case.own_ids[:count]
    response = await _post(case, selected)
    assert response.status_code == 200, response.text
    assert response.json()["deleted_count"] == count
    assert response.json()["deleted_submission_ids"] == [str(item) for item in selected]
    assert response.json()["deleted_notifications"] == count
    assert response.json()["storage_cleanup_deferred"] is True
    remaining = set((await db_session.execute(select(PassportSubmissionModel.id))).scalars())
    assert remaining == case.all_ids - set(selected)
    notifications = set((await db_session.execute(select(NotificationModel.entity_id))).scalars())
    assert notifications == {str(item) for item in remaining}
    assert await db_session.get(ClientGroupModel, case.group_id) is not None
    jobs = (await db_session.execute(select(StorageCleanupJobModel))).scalars().all()
    assert sum(job.object_count for job in jobs) == count
    audits = await _audits(case)
    assert set(audits) == {"destructive_operation_attempted", "passport_submissions_bulk_deleted"}
    completed = audits["passport_submissions_bulk_deleted"]
    assert completed.user_id == case.actor.id
    assert completed.entity_id == str(case.group_id)
    assert completed.metadata_json["deleted_count"] == count
    assert completed.metadata_json["deleted_submission_ids"] == [str(item) for item in selected]
    propagate, cleanup = external_effects
    propagate.assert_awaited_once()
    assert propagate.await_args.kwargs["passenger_submission_ids"] == selected
    assert propagate.await_args.kwargs["operation"] == "delete"
    assert cleanup.await_count == len(jobs)


@pytest.mark.parametrize(
    ("role", "access"),
    [
        (UserRole.AGENCY_STAFF, "owned"),
        (UserRole.AGENCY_STAFF, "assigned"),
        (UserRole.AGENCY_COORDINATOR, "owned"),
        (UserRole.CLIENT_MANAGER, "owned"),
    ],
)
async def test_non_delete_roles_are_denied_even_for_owned_or_assigned_groups(
    db_session: AsyncSession, external_effects, role: UserRole, access: str
) -> None:
    case = await _seed(db_session, role=role, access=access)
    response = await _post(case, case.own_ids[:2])
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "AUTHORIZATION_ERROR"
    await _assert_retained(case, external_effects)
    audits = await _audits(case)
    assert set(audits) == {"destructive_operation_attempted", "destructive_operation_denied"}
    denied = audits["destructive_operation_denied"]
    assert denied.user_id == case.actor.id
    assert denied.entity_id == str(case.group_id)
    assert denied.metadata_json["target_count"] == 2
    assert denied.metadata_json["reason_code"] == "AUTHORIZATION_ERROR"


async def test_manager_cannot_discover_or_delete_foreign_group(
    db_session: AsyncSession, external_effects
) -> None:
    case = await _seed(db_session)
    response = await _post(case, [case.foreign_submission_id], group_id=case.foreign_group_id)
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert "Foreign group" not in response.text
    await _assert_retained(case, external_effects)
    assert not await _audits(case)


@pytest.mark.parametrize("selection_kind", ["other_group", "foreign_tenant", "missing"])
async def test_manager_mixed_selection_is_all_or_nothing(
    db_session: AsyncSession, external_effects, selection_kind: str
) -> None:
    case = await _seed(db_session)
    invalid_id = {
        "other_group": case.other_submission_id,
        "foreign_tenant": case.foreign_submission_id,
        "missing": uuid.uuid4(),
    }[selection_kind]
    response = await _post(case, [case.own_ids[0], invalid_id])
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "PASSPORT_DELETE_SELECTION_STALE"
    await _assert_retained(case, external_effects)
    audits = await _audits(case)
    assert set(audits) == {"destructive_operation_attempted", "destructive_operation_blocked"}
    blocked = audits["destructive_operation_blocked"]
    assert blocked.metadata_json["reason_code"] == "PASSPORT_DELETE_SELECTION_STALE"
    assert blocked.user_id == case.actor.id


async def test_manager_submission_delete_respects_legal_hold(
    db_session: AsyncSession, external_effects
) -> None:
    case = await _seed(db_session, held=True)
    response = await _post(case, case.own_ids)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "PASSPORT_LEGAL_HOLD_ACTIVE"
    await _assert_retained(case, external_effects)
    audits = await _audits(case)
    assert set(audits) == {"destructive_operation_attempted", "destructive_operation_blocked"}
    blocked = audits["destructive_operation_blocked"]
    assert blocked.metadata_json["reason_code"] == "PASSPORT_LEGAL_HOLD_ACTIVE"
    assert "Confidential legal review" not in str(blocked.metadata_json)


async def test_manager_still_cannot_permanently_delete_group_with_default_policy_scope(
    db_session: AsyncSession, external_effects
) -> None:
    case = await _seed(db_session, access="owned")
    with pytest.raises(AuthorizationError):
        await DestructiveMutationPolicy(db_session).require_group(
            user=case.actor,
            group_id=case.group_id,
            action="client_group_permanent_delete",
        )
    await _assert_retained(case, external_effects)
    audits = await _audits(case)
    assert set(audits) == {"destructive_operation_attempted", "destructive_operation_denied"}
    assert audits["destructive_operation_denied"].metadata_json["operation"] == (
        "client_group_permanent_delete"
    )
