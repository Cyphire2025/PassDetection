"""Real staff invitations and legacy-account security-state initialization."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import AuditLogModel, UserModel, UserSecurityStateModel
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.presentation.api.v1.routes import (
    admin_accounts,
    managed_account_creation,
    managed_account_credentials,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    CreateStaffRequest,
    ResetManagedAccountPasswordRequest,
)
from tests.integration.test_admin_workforce_contracts import _actor
from tests.persistence import persist_graph


def _request() -> Request:
    return Request({"type": "http", "headers": [], "client": ("127.0.0.1", 12345)})


@pytest.mark.parametrize(
    "role", [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]
)
async def test_staff_invitation_is_private_single_use_and_agency_scoped(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    role: UserRole,
) -> None:
    actor = await _actor(db_session, role)
    monkeypatch.setattr(managed_account_creation, "hash_password", lambda _value: "fixture-hash")
    response = Response()
    invited = await admin_accounts.create_staff_account(
        body=CreateStaffRequest(full_name="  Synthetic Staff  ", email="STAFF@example.com"),
        request=_request(),
        response=response,
        current_user=actor,
        session=db_session,
    )
    assert invited.email == "staff@example.com" and invited.full_name == "Synthetic Staff"
    assert invited.role == UserRole.AGENCY_STAFF.value and invited.agency_id == actor.agency_id
    assert invited.agency_name == "Synthetic workforce" and invited.credential_state == "invited"
    state = await db_session.get(UserSecurityStateModel, invited.id)
    assert state and state.mfa_required and state.session_version == 1
    assert invited.activation_token
    token = await IdentitySecurityRepository(db_session).get_valid_action_token(
        raw_token=invited.activation_token,
        purpose="activation",
    )
    assert token and token.user_id == invited.id and token.created_by_user_id == actor.id
    assert token.token_hash != invited.activation_token and len(token.token_hash) == 64
    audit = (
        await db_session.scalars(
            select(AuditLogModel).where(AuditLogModel.action == "staff.invited")
        )
    ).one()
    assert invited.activation_token not in json.dumps(audit.metadata_json)
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    listed = await admin_accounts.list_staff_accounts(current_user=actor, session=db_session)
    assert len(listed) == 1 and listed[0].id == invited.id and listed[0].activation_token is None


@pytest.mark.parametrize("reason,status_code", [("unassigned", 400), ("duplicate", 409)])
async def test_rejected_staff_invitation_has_no_credential_or_audit_side_effect(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    status_code: int,
) -> None:
    actor = await _actor(db_session)
    if reason == "unassigned":
        actor.agency_id = None

    def forbidden_password(_value: str) -> str:
        raise AssertionError("Rejected invitation attempted credential generation")

    monkeypatch.setattr(managed_account_creation, "hash_password", forbidden_password)
    with pytest.raises(HTTPException) as rejected:
        await admin_accounts.create_staff_account(
            body=CreateStaffRequest(full_name="Synthetic Staff", email="OWNER@example.com"),
            request=_request(),
            response=Response(),
            current_user=actor,
            session=db_session,
        )
    assert rejected.value.status_code == status_code
    assert await db_session.scalar(select(func.count()).select_from(UserModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(AuditLogModel)) == 0


@pytest.mark.parametrize("operation", ["revoke", "password", "mfa"])
async def test_legacy_account_without_security_row_is_initialized_before_revocation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    actor = await _actor(db_session)
    subject_id = uuid.uuid4()
    await persist_graph(
        db_session,
        [
            UserModel(
                id=subject_id,
                agency_id=actor.agency_id,
                role=UserRole.AGENCY_STAFF.value,
                email="legacy@example.com",
                full_name="Synthetic legacy",
                hashed_password="fixture-hash",
            )
        ],
    )
    assert await db_session.get(UserSecurityStateModel, subject_id) is None
    monkeypatch.setattr(
        managed_account_credentials, "hash_password", lambda _value: "reset-fixture-hash"
    )
    if operation == "password":
        response = Response()
        result = await admin_accounts.reset_managed_account_password(
            subject_id,
            ResetManagedAccountPasswordRequest(),
            _request(),
            response,
            actor,
            db_session,
        )
        assert result.credential_state == "invited" and result.activation_token
        assert "no-store" in response.headers["cache-control"]
    elif operation == "mfa":
        result = await admin_accounts.reset_managed_account_mfa(
            subject_id, _request(), actor, db_session
        )
        assert result.status_code == 204
    else:
        result = await admin_accounts.revoke_managed_account_sessions(
            subject_id, _request(), actor, db_session
        )
        assert result.status_code == 204
    await db_session.flush()
    state = await db_session.get(UserSecurityStateModel, subject_id)
    assert state and state.session_version > 1
    assert state.credential_state == ("invited" if operation == "password" else "active")
