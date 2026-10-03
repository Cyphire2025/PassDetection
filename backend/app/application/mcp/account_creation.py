"""Invited business accounts with retained history and no MCP credential disclosure."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.application.mcp.access_changes import require_access_mfa
from app.application.mcp.change_context import require_change_actor
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
)
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository

WORKFORCE_ROLES = {
    "coordinator": "agency_coordinator",
    "staff": "agency_staff",
    "manager": "agency_manager",
}
ACCOUNT_PATHS = {
    "coordinator": "/tour-operations/coordinators",
    "staff": "/staff",
    "manager": "/admin",
}


@dataclass(frozen=True, slots=True)
class ClientManagerCreationSupport:
    organization: Callable[..., Awaitable[Any]]
    groups: Callable[..., Awaitable[dict[uuid.UUID, Any]]]
    normalize_phone: Callable[[str], str | None]
    invitation_hash: Callable[..., str]


async def account_creation_scope(
    context: MCPDatabaseContext, agency_id: uuid.UUID, *, workforce: bool = False
) -> User:
    actor = await require_change_actor(context, agency_id)
    await require_access_mfa(context)
    # The canonical workforce administration routes create in the actor's agency.
    if workforce and actor.agency_id != agency_id:
        raise MCPOperationError("account_creation_actor_agency_required")
    return actor


async def create_workforce(context: MCPDatabaseContext, body: Any) -> MCPDatabaseResult:
    actor = await account_creation_scope(context, body.agency_id, workforce=True)
    if body.account_type not in WORKFORCE_ROLES:
        raise MCPOperationError("account_creation_invalid_role")
    email = str(body.email).lower().strip()
    if (
        await context.session.scalar(select(UserModel.id).where(UserModel.email == email))
        is not None
    ):
        raise MCPOperationError("account_creation_identity_conflict")
    account = UserModel(
        id=uuid.uuid4(),
        agency_id=body.agency_id,
        email=email,
        full_name=" ".join(body.full_name.split()),
        role=WORKFORCE_ROLES[body.account_type],
        hashed_password=await run_password_work(hash_password, "Inv1" + secrets.token_urlsafe(32)),
        is_active=True,
    )
    context.session.add(account)
    await context.session.flush()
    context.session.add(
        UserSecurityStateModel(
            user_id=account.id, credential_state="invited", session_version=1, mfa_required=True
        )
    )
    # Keep the canonical activation lifecycle; only its hash is durable. A fresh
    # link is obtained through the existing dashboard reset action, never MCP.
    await IdentitySecurityRepository(context.session).issue_action_token(
        user_id=account.id,
        purpose="activation",
        expires_in=timedelta(days=7),
        created_by_user_id=actor.id,
    )
    audit = await AuditLogRepository(context.session).record(
        action=f"{body.account_type}.invited",
        entity_type="user_account",
        entity_id=str(account.id),
        agency_id=body.agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        metadata={
            "target_role": account.role,
            "target_email": email,
            "mcp_operation_id": str(context.operation_id),
        },
    )
    path = ACCOUNT_PATHS[body.account_type]
    return MCPDatabaseResult(
        {
            "account_id": str(account.id),
            "agency_id": str(body.agency_id),
            "account_type": body.account_type,
            "credential_state": "invited",
            "activation_required": True,
            "activation_delivery": "dashboard_only",
            "credential_setup_path": path,
            "next_step": "Use the dashboard account reset/activation action to obtain a fresh one-time activation link and deliver it explicitly.",
            "notifications_sent": 0,
            "business_audit_id": str(audit.id),
        },
        created_entities=(MCPCreatedEntity("user_account", str(account.id), path),),
    )


async def authorize_account_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
    data = receipt["data"]
    await account_creation_scope(
        context, uuid.UUID(data["agency_id"]), workforce=data.get("account_type") in WORKFORCE_ROLES
    )
    account = await context.session.scalar(
        select(UserModel).where(
            UserModel.id == uuid.UUID(data["account_id"]),
            UserModel.agency_id == uuid.UUID(data["agency_id"]),
            UserModel.deleted_at.is_(None),
            UserModel.is_active.is_(True),
        )
    )
    expected_role = WORKFORCE_ROLES.get(data.get("account_type"), "client_manager")
    if account is None or account.role != expected_role:
        raise MCPOperationError("account_creation_receipt_unavailable")
    if expected_role == "client_manager":
        profile = await context.session.scalar(
            select(ClientManagerProfileModel).where(
                ClientManagerProfileModel.id == uuid.UUID(data["profile_id"]),
                ClientManagerProfileModel.user_id == account.id,
                ClientManagerProfileModel.agency_id == account.agency_id,
                ClientManagerProfileModel.organization_id == uuid.UUID(data["organization_id"]),
                ClientManagerProfileModel.deleted_at.is_(None),
                ClientManagerProfileModel.status.in_(("invited", "active")),
            )
        )
        if profile is None:
            raise MCPOperationError("account_creation_receipt_unavailable")


async def create_client_manager(
    context: MCPDatabaseContext, body: Any, support: ClientManagerCreationSupport
) -> MCPDatabaseResult:
    actor = await account_creation_scope(context, body.agency_id)
    organization = await support.organization(
        context.session, body.agency_id, body.organization_id, lock=True
    )
    groups = await support.groups(context.session, body.agency_id, organization.id, body.group_ids)
    phone = support.normalize_phone(body.phone_number)
    if phone is None:
        raise MCPOperationError("account_creation_invalid_phone")
    email = str(body.email).lower().strip()
    if (
        await context.session.scalar(select(UserModel.id).where(UserModel.email == email))
        is not None
    ):
        raise MCPOperationError("account_creation_identity_conflict")
    if (
        await context.session.scalar(
            select(ClientManagerProfileModel.id).where(
                ClientManagerProfileModel.agency_id == body.agency_id,
                ClientManagerProfileModel.normalized_phone_number == phone,
                ClientManagerProfileModel.deleted_at.is_(None),
            )
        )
        is not None
    ):
        raise MCPOperationError("account_creation_identity_conflict")
    now = datetime.now(UTC)
    account = UserModel(
        id=uuid.uuid4(),
        agency_id=body.agency_id,
        email=email,
        full_name=" ".join(body.full_name.split()),
        role="client_manager",
        is_active=True,
        hashed_password=await run_password_work(hash_password, "Gc1" + secrets.token_urlsafe(32)),
        created_at=now,
        updated_at=now,
    )
    context.session.add(account)
    await context.session.flush()
    profile = ClientManagerProfileModel(
        id=uuid.uuid4(),
        agency_id=body.agency_id,
        user_id=account.id,
        organization_id=organization.id,
        normalized_phone_number=phone,
        status="invited",
        force_password_change=False,
        invitation_token_hash=support.invitation_hash(
            secrets.token_urlsafe(32), purpose="manager-invitation"
        ),
        invitation_expires_at=now + timedelta(days=7),
        activated_at=None,
        access_generation=1,
        revision=1,
        created_by_user_id=actor.id,
        updated_by_user_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    context.session.add(profile)
    await context.session.flush()
    context.session.add_all(
        [
            ClientManagerGroupAssignmentModel(
                id=uuid.uuid4(),
                agency_id=body.agency_id,
                organization_id=organization.id,
                group_id=group_id,
                profile_id=profile.id,
                gc_group_access_id=access.id,
                is_active=True,
                can_view_passenger_names=False,
                personal_document_access_enabled=False,
                assigned_by_user_id=actor.id,
                assigned_at=now,
                updated_at=now,
            )
            for group_id, access in groups.items()
        ]
    )
    await context.session.flush()
    audit = await AuditLogRepository(context.session).record(
        action="gc_app.client_manager_created",
        entity_type="client_manager_profile",
        entity_id=str(profile.id),
        agency_id=body.agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        metadata={"group_count": len(groups), "mcp_operation_id": str(context.operation_id)},
    )
    path = "/gc-app/client-manager-accounts"
    return MCPDatabaseResult(
        {
            "account_id": str(account.id),
            "profile_id": str(profile.id),
            "agency_id": str(body.agency_id),
            "account_type": "client_manager",
            "organization_id": str(organization.id),
            "group_ids": [str(value) for value in body.group_ids],
            "credential_state": "invited",
            "activation_required": True,
            "activation_delivery": "dashboard_only",
            "credential_setup_path": path,
            "next_step": "Use Issue reset link in GC App Client Manager Accounts to obtain and explicitly deliver a fresh activation link.",
            "notifications_sent": 0,
            "business_audit_id": str(audit.id),
        },
        created_entities=(MCPCreatedEntity("client_manager_profile", str(profile.id), path),),
    )
