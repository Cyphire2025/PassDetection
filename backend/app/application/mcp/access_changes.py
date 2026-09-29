"""Revision-fenced, additive application group permissions with fresh MFA."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select

from app.application.mcp.change_context import require_change_actor
from app.application.mcp.credentials import utc
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.use_cases.client_groups.group_access import (
    add_missing_group_access,
    assignable_group_predicates,
    explicit_access_group_ids,
)
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.models import ClientGroupModel, ManagerGroupAccessModel, UserModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

AccessKind = Literal["add_staff_group_access", "add_manager_group_access"]
AccountType = Literal["staff", "manager"]
MAX_RETAINED_ASSIGNMENTS = 5000


@dataclass(frozen=True, slots=True)
class AccessCommand:
    agency_id: uuid.UUID
    account_id: uuid.UUID
    group_ids: list[uuid.UUID]
    expected_revision: str


async def require_access_mfa(context: MCPDatabaseContext) -> None:
    mfa_at = await context.session.scalar(
        select(MCPGrantModel.mfa_at).where(
            MCPGrantModel.id == context.principal.grant_id,
            MCPGrantModel.user_id == context.principal.user_id,
        )
    )
    # Same current ten-minute policy as the website's require_recent_mfa.
    if mfa_at is None or not -60 <= (datetime.now(UTC) - utc(mfa_at)).total_seconds() <= 600:
        raise MCPOperationError("group_access_recent_mfa_required")


async def access_scope(
    context: MCPDatabaseContext,
    *,
    agency_id: uuid.UUID,
    account_id: uuid.UUID,
    account_type: AccountType,
    group_ids: list[uuid.UUID],
    lock: bool = False,
) -> tuple[UserModel, list[ClientGroupModel], list[ManagerGroupAccessModel]]:
    await require_change_actor(context, agency_id)
    if not 1 <= len(group_ids) <= 100 or len(set(group_ids)) != len(group_ids):
        raise MCPOperationError("group_access_invalid_selection")
    account = await context.session.scalar(
        select(UserModel)
        .where(
            UserModel.id == account_id,
            UserModel.agency_id == agency_id,
            UserModel.role == ("agency_staff" if account_type == "staff" else "agency_manager"),
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
        )
        .with_for_update(read=not lock)
        .execution_options(populate_existing=True)
    )
    if account is None:
        raise MCPOperationError("group_access_account_unavailable")
    groups = list(
        (
            await context.session.scalars(
                select(ClientGroupModel)
                .where(
                    ClientGroupModel.id.in_(group_ids),
                    *assignable_group_predicates(agency_id),
                    ClientGroupModel.deleted_at.is_(None),
                )
                .order_by(ClientGroupModel.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if {group.id for group in groups} != set(group_ids):
        raise MCPOperationError("group_access_group_unavailable")
    existing = list(
        (
            await context.session.scalars(
                select(ManagerGroupAccessModel)
                .where(
                    ManagerGroupAccessModel.manager_id == account_id,
                )
                .order_by(ManagerGroupAccessModel.id)
                .limit(MAX_RETAINED_ASSIGNMENTS + 1)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(existing) > MAX_RETAINED_ASSIGNMENTS:
        raise MCPOperationError("group_access_scope_too_large")
    if any(row.agency_id != agency_id for row in existing):
        raise MCPOperationError("group_access_history_scope_invalid")
    return account, groups, existing


def access_revision(
    account: UserModel,
    groups: list[ClientGroupModel],
    existing: list[ManagerGroupAccessModel],
) -> str:
    source = {
        "account": [str(account.id), str(account.agency_id), account.role, account.is_active],
        "groups": [
            [
                str(group.id),
                group.status,
                str(group.created_by_user_id),
                group.name,
                group.roster_revision,
            ]
            for group in groups
        ],
        "assignments": [
            [str(row.id), str(row.group_id), str(row.agency_id), utc(row.created_at).isoformat()]
            for row in existing
        ],
    }
    return hashlib.sha256(json.dumps(source, separators=(",", ":")).encode()).hexdigest()


async def inspect_group_access(
    context: MCPDatabaseContext,
    *,
    agency_id: uuid.UUID,
    account_id: uuid.UUID,
    account_type: AccountType,
    group_ids: list[uuid.UUID],
) -> dict[str, Any]:
    account, groups, existing = await access_scope(
        context,
        agency_id=agency_id,
        account_id=account_id,
        account_type=account_type,
        group_ids=group_ids,
    )
    explicit = set(explicit_access_group_ids(groups, account.id))
    assigned = {row.group_id for row in existing}
    return {
        "agency_id": str(agency_id),
        "account_id": str(account_id),
        "account_type": account_type,
        "access_revision": access_revision(account, groups, existing),
        "retained_assignment_count": len(existing),
        "selected_groups": [
            {
                "group_id": str(group.id),
                "name": group.name[:160],
                "access": "owned"
                if group.id not in explicit
                else "assigned"
                if group.id in assigned
                else "not_assigned",
            }
            for group in groups
        ],
        "content_trust": "untrusted_business_data",
        "completeness": "complete",
        "notice": "Only the explicit selected groups are listed. Existing unrelated assignments are retained. New access requires MFA from the last ten minutes.",
    }


def group_access_operation(
    kind: AccessKind,
    validate: Callable[[dict[str, Any]], AccessCommand],
) -> MCPDatabaseOperation:
    if kind not in {"add_staff_group_access", "add_manager_group_access"}:
        raise ValueError("Unsupported account access operation")
    account_type: AccountType = "staff" if kind == "add_staff_group_access" else "manager"

    async def add(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = validate(payload)
        await require_access_mfa(context)
        account, groups, existing = await access_scope(
            context,
            agency_id=command.agency_id,
            account_id=command.account_id,
            account_type=account_type,
            group_ids=command.group_ids,
            lock=True,
        )
        if access_revision(account, groups, existing) != command.expected_revision:
            raise MCPOperationError("group_access_revision_changed")
        explicit = set(explicit_access_group_ids(groups, account.id))
        missing = explicit - {row.group_id for row in existing}
        if len(existing) + len(missing) > MAX_RETAINED_ASSIGNMENTS:
            raise MCPOperationError("group_access_scope_too_large")
        added = await add_missing_group_access(
            context.session, account=account, groups=groups, existing=existing
        )
        selected = set(command.group_ids)
        data = {
            "agency_id": str(command.agency_id),
            "account_id": str(account.id),
            "account_type": account_type,
            "group_ids": [str(group.id) for group in groups],
            "added_assignment_ids": [str(row.id) for row in added],
            "retained_selected_assignment_ids": [
                str(row.id) for row in existing if row.group_id in selected
            ],
            "assignment_bindings": [
                {"assignment_id": str(row.id), "group_id": str(row.group_id)}
                for row in [*existing, *added]
                if row.group_id in selected
            ],
            "owned_group_ids": [str(group.id) for group in groups if group.id not in explicit],
            "retained_assignment_count": len(existing),
            "added_count": len(added),
        }
        audit = await AuditLogRepository(context.session).record(
            action="application_group_access_added",
            entity_type="user",
            entity_id=str(account.id),
            agency_id=command.agency_id,
            user_id=context.principal.user_id,
            metadata={"mcp_operation_id": str(context.operation_id), **data},
        )
        data["business_audit_id"] = str(audit.id)
        return MCPDatabaseResult(
            data,
            created_entities=tuple(
                MCPCreatedEntity("group_access", str(row.id), f"/passports/groups/{row.group_id}")
                for row in added
            ),
        )

    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        await require_access_mfa(context)
        data = receipt["data"]
        account, groups, existing = await access_scope(
            context,
            agency_id=uuid.UUID(data["agency_id"]),
            account_id=uuid.UUID(data["account_id"]),
            account_type=account_type,
            group_ids=[uuid.UUID(value) for value in data["group_ids"]],
        )
        wanted = {(row["assignment_id"], row["group_id"]) for row in data["assignment_bindings"]}
        if not wanted <= {(str(row.id), str(row.group_id)) for row in existing}:
            raise MCPOperationError("group_access_receipt_unavailable")
        if not set(data["owned_group_ids"]) <= {
            str(group.id) for group in groups if group.created_by_user_id == account.id
        }:
            raise MCPOperationError("group_access_receipt_unavailable")

    return MCPDatabaseOperation(
        MCPToolPolicy(kind, MCPCapability.CHANGE, frozenset({"add_application_group_access"})),
        add,
        authorize_receipt,
    )
