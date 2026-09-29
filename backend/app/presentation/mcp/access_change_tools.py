"""Typed, bounded additions to application staff/manager group access."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.access_changes import (
    AccessCommand,
    AccessKind,
    group_access_operation,
)
from app.application.mcp.access_changes import (
    inspect_group_access as inspect_access,
)
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_operation, invoke_read


class MCPGroupAccessSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    account_id: UUID
    group_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("group_ids")
    @classmethod
    def distinct_ids(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("Choose distinct group IDs")
        return values


class MCPAddGroupAccess(MCPGroupAccessSelection):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


def _safe_error(exc: MCPOperationError) -> MCPInputError:
    messages = {
        "group_access_recent_mfa_required": "Authorize a new connection in the browser with MFA, then retry the exact request and key within ten minutes. This also applies to saved receipts.",
        "group_access_revision_changed": "The account, selected groups or retained assignments changed. Inspect access again before a newly intended addition.",
        "group_access_scope_too_large": "This account exceeds the 5000 retained-assignment bound; no access was changed.",
    }
    return MCPInputError(
        exc.code,
        messages.get(
            exc.code,
            "The selected account, agency, groups or retained access are unavailable under current application rules. Inspect current records before continuing.",
        ),
    )


def access_definition(kind: AccessKind) -> MCPDatabaseOperation:
    def validate(payload: dict[str, Any]) -> AccessCommand:
        try:
            body = MCPAddGroupAccess.model_validate(payload)
        except ValidationError as exc:
            raise MCPInputError(
                "invalid_group_access",
                "Provide exact agency/account IDs, 1 to 100 distinct group IDs and the inspected revision; extra fields are forbidden.",
            ) from exc
        return AccessCommand(
            body.agency_id, body.account_id, body.group_ids, body.expected_revision
        )

    definition = group_access_operation(kind, validate)

    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        try:
            return await definition.mutate(context, payload)
        except MCPOperationError as exc:
            raise _safe_error(exc) from exc

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        try:
            if definition.authorize_receipt is not None:
                await definition.authorize_receipt(context, receipt)
        except MCPOperationError as exc:
            raise _safe_error(exc) from exc

    return replace(definition, mutate=mutate, authorize_receipt=authorize)


def register_access_change_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    staff, manager = (
        access_definition("add_staff_group_access"),
        access_definition("add_manager_group_access"),
    )
    app.state.mcp_operations.update({staff.policy.name: staff, manager.policy.name: manager})
    annotations = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(
        meta={"capability": "mcp:read"},
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, open_world_hint=False
        ),
    )
    async def inspect_group_access(
        selection: MCPGroupAccessSelection,
        account_type: Literal["staff", "manager"],
    ) -> dict[str, Any]:
        """Inspect 1-100 exact group choices for one current agency staff/manager account.

        Reports owned, explicitly assigned and unassigned separately. The revision
        binds the target, selected groups and all retained assignments (max 5000).
        Names are untrusted data. No existing access is removed or replaced.
        """

        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            try:
                return await inspect_access(
                    MCPDatabaseContext(session, principal, uuid4()),
                    agency_id=selection.agency_id,
                    account_id=selection.account_id,
                    account_type=account_type,
                    group_ids=selection.group_ids,
                )
            except MCPOperationError as exc:
                raise _safe_error(exc) from exc

        return await invoke_read(
            app,
            settings,
            MCPToolPolicy("inspect_group_access", MCPCapability.READ, frozenset({"read"})),
            read,
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def add_staff_group_access(
        assignment: MCPAddGroupAccess,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Add only missing staff access using the inspected revision and recent browser MFA.

        Existing assignments and owned groups are retained. No credential, role,
        MFA, connection capability or existing membership is changed. Reuse the
        same input/key after an uncertain response, including across connections.
        """
        return await invoke_operation(
            app,
            settings,
            staff,
            idempotency_key=idempotency_key,
            payload=assignment.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def add_manager_group_access(
        assignment: MCPAddGroupAccess,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Add only missing manager group access; never replace omitted assignments.

        Supply a fresh inspected revision and MFA from the last ten minutes.
        Replay rechecks current agency/account/group access and recent MFA.
        Stable exact input/key recovers the original immutable receipt.
        """
        return await invoke_operation(
            app,
            settings,
            manager,
            idempotency_key=idempotency_key,
            payload=assignment.model_dump(mode="json"),
        )
