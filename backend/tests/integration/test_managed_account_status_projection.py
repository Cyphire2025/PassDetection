"""Status changes must report the persisted credential lifecycle accurately."""

from __future__ import annotations

import uuid

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from app.presentation.api.v1.routes import admin_accounts
from app.presentation.api.v1.schemas.operations_schemas import SetManagedAccountStatusRequest
from tests.integration.test_admin_workforce_contracts import _actor
from tests.persistence import persist_graph


@pytest.mark.parametrize("role", [UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR])
@pytest.mark.parametrize("credential_state", ["invited", "active"])
@pytest.mark.parametrize("is_active", [True, False])
async def test_status_response_preserves_invited_or_active_state_and_fences_sessions(
    db_session: AsyncSession,
    role: UserRole,
    credential_state: str,
    is_active: bool,
) -> None:
    actor = await _actor(db_session)
    account_id = uuid.uuid4()
    account = UserModel(
        id=account_id,
        email="synthetic-managed@example.com",
        full_name="Synthetic managed account",
        hashed_password="fixture-hash",
        agency_id=actor.agency_id,
        role=role.value,
    )
    state = UserSecurityStateModel(
        user_id=account_id,
        credential_state=credential_state,
        session_version=4,
        mfa_required=True,
    )
    await persist_graph(db_session, [account, state])
    result = await admin_accounts.set_managed_account_status(
        account_id=account_id,
        body=SetManagedAccountStatusRequest(is_active=is_active),
        request=Request({"type": "http", "headers": [], "client": ("127.0.0.1", 12345)}),
        current_user=actor,
        session=db_session,
    )
    await db_session.flush()
    assert account.is_active is is_active and result.is_active is is_active
    assert state.session_version == 5 and state.mfa_required is True
    assert state.credential_state == credential_state
    assert result.activation_token is None
    listed = await admin_accounts.list_managed_accounts(current_user=actor, session=db_session)
    assert len(listed) == 1 and listed[0].credential_state == credential_state
    assert result.credential_state == credential_state
