"""Validated managed-account responses and account audit events."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.operations_schemas import (
    ManagedAccountResponse,
)
from app.presentation.security.client_ip import trusted_client_ip

_CredentialState = Literal["invited", "active"]


def _validated_credential_state(value: str) -> _CredentialState:
    if value not in {"invited", "active"}:
        raise RuntimeError("Invalid persisted workforce credential state.")
    return cast(_CredentialState, value)


async def _audit_account_action(
    session: AsyncSession,
    current_user: User,
    request: Request,
    account: UserModel,
    action: str,
    metadata: dict[str, object] | None = None,
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type="user_account",
        agency_id=account.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(account.id),
        ip_address=trusted_client_ip(request),
        metadata={"target_role": account.role, "target_email": account.email, **(metadata or {})},
    )


def _account_response(
    account: UserModel,
    agency_name: str | None,
    security_state: UserSecurityStateModel | None = None,
    *,
    activation_token: str | None = None,
) -> ManagedAccountResponse:
    return ManagedAccountResponse(
        id=account.id,
        full_name=account.full_name,
        email=account.email,
        role=account.role,
        agency_id=account.agency_id,
        agency_name=agency_name,
        is_active=account.is_active,
        created_at=account.created_at,
        last_login_at=account.last_login_at,
        credential_state=(
            _validated_credential_state(security_state.credential_state)
            if security_state
            else "active"
        ),
        activation_token=activation_token,
    )
