"""Typed one-broadcast additions with source/revision and retained-effect guards."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.broadcast_link_changes import (
    BroadcastLinkCommand,
    broadcast_link_operation,
    inspect_link_addition,
)
from app.application.mcp.broadcast_link_source import BroadcastLinkSource
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.api.v1.routes.client_group_broadcast_configuration import (
    requested_link_configuration,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import _matching_field_options
from app.presentation.api.v1.schemas.client_group_schemas import WhatsAppBroadcastSummaryResponse
from app.presentation.mcp.invocation import MCPInputError, invoke_operation, invoke_read


class MCPBroadcastLinkSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    group_id: UUID
    broadcast_id: UUID
    matching_field_keys: list[Annotated[str, Field(min_length=1, max_length=128)]] | None = Field(
        default=None, min_length=1, max_length=256
    )

    @field_validator("matching_field_keys")
    @classmethod
    def distinct_fields(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and len(set(values)) != len(values):
            raise ValueError("Choose distinct matching fields")
        return values


class MCPAddBroadcastLink(MCPBroadcastLinkSelection):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


def _command(body: MCPBroadcastLinkSelection) -> BroadcastLinkCommand:
    return BroadcastLinkCommand(
        body.agency_id,
        body.group_id,
        body.broadcast_id,
        body.matching_field_keys,
        body.expected_revision if isinstance(body, MCPAddBroadcastLink) else None,
    )


def _matching_fields(source: BroadcastLinkSource, fields: list[str] | None) -> list[str] | None:
    row = source.broadcast
    summary = WhatsAppBroadcastSummaryResponse(
        id=row.id,
        name=row.name,
        archived_at=row.archived_at,
        recipient_count=len(source.recipients),
        available_matching_fields=_matching_field_options(row.imported_field_keys),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    try:
        selected = requested_link_configuration(
            [summary], [row.id], {}, None if fields is None else {row.id: fields}
        )[row.id]
    except HTTPException as exc:
        raise MCPInputError(
            "broadcast_link_invalid_matching_fields",
            "Select only current available matching fields; omit the field list to use legacy matching.",
        ) from exc
    return list(selected) if selected is not None else None


def _failure(exc: MCPOperationError) -> MCPInputError:
    messages = {
        "broadcast_link_revision_changed": "The link, source roster, recipients or mobile proposal changed. Inspect a fresh exact proposal before a new intended addition.",
        "broadcast_link_private_delivery_pending": "A private delivery is queued, processing or unknown. Inspect its status first; this operation cannot cancel it.",
        "broadcast_link_mobile_change_required": "The canonical mobile plan would change an existing identity or session. Resolve that workflow explicitly before adding this link.",
        "broadcast_link_recipient_unavailable": "A source phone collides with a removed, merged or suppressed recipient. This operation cannot revive it.",
        "broadcast_link_retained_contact_conflict": "An existing source contact has different identity data. This operation preserves it and cannot overwrite it.",
        "broadcast_link_retained_override": "A retained traveller phone override requires explicit review; this operation cannot change or discard it.",
        "broadcast_link_existing_configuration": "The link already exists with different matching fields. This operation cannot replace its configuration.",
        "broadcast_link_replacement_conflict": "The proposed link conflicts with a retained replacement decision. No recipient suppression or removal is allowed here.",
        "broadcast_link_scope_too_large": "The proposal exceeds 100 links or 5000 retained/source rows; no additions were applied.",
        "broadcast_link_recipient_capacity": "The proposed additions exceed the canonical 1500 active-recipient limit; no rows were added.",
    }
    return MCPInputError(
        exc.code,
        messages.get(
            exc.code,
            "The selected group, broadcast or retained receipt is unavailable under current application policy.",
        ),
    )


def broadcast_link_definition() -> MCPDatabaseOperation:
    def validate(payload: dict[str, Any]) -> BroadcastLinkCommand:
        try:
            return _command(MCPAddBroadcastLink.model_validate(payload))
        except ValidationError as exc:
            raise MCPInputError(
                "invalid_broadcast_link",
                "Provide exact agency/group/broadcast IDs, documented matching fields and the inspected SHA-256 revision.",
            ) from exc

    definition = broadcast_link_operation(validate, _matching_fields)

    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        try:
            return await definition.mutate(context, payload)
        except MCPOperationError as exc:
            raise _failure(exc) from exc

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        try:
            if definition.authorize_receipt is not None:
                await definition.authorize_receipt(context, receipt)
        except MCPOperationError as exc:
            raise _failure(exc) from exc

    return replace(definition, mutate=mutate, authorize_receipt=authorize)


def register_broadcast_link_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    definition = broadcast_link_definition()
    app.state.mcp_operations[definition.policy.name] = definition

    @server.tool(
        meta={"capability": "mcp:read"},
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, open_world_hint=False
        ),
    )
    async def inspect_group_broadcast_addition(
        selection: MCPBroadcastLinkSelection,
    ) -> dict[str, Any]:
        """Inspect one exact group/broadcast addition and its retained-effect boundaries.

        Import-only sources retain every traveller row and reuse unchanged active
        shared-phone destinations; at most 5000 source/retained rows,100 links and
        1500 active recipients. Any collision requiring revival, replacement or
        mobile binding/session changes blocks the complete proposal. No sends.
        """

        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            try:
                return await inspect_link_addition(
                    MCPDatabaseContext(session, principal, uuid4()),
                    _command(selection),
                    _matching_fields,
                )
            except MCPOperationError as exc:
                raise _failure(exc) from exc

        return await invoke_read(
            app,
            settings,
            MCPToolPolicy(
                "inspect_group_broadcast_addition", MCPCapability.READ, frozenset({"read"})
            ),
            read,
        )

    @server.tool(
        meta={"capability": "mcp:change"},
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def add_group_broadcast_link(
        association: MCPAddBroadcastLink,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Add one inspected group/broadcast link, retaining every previous row.

        New import-only source contacts/recipients and eligible new mobile
        identities may be added. Existing identities, sessions, recipients,
        overrides and private deliveries remain unchanged. Nothing is sent.
        Reuse the same exact input and key after an uncertain response.
        """
        return await invoke_operation(
            app,
            settings,
            definition,
            idempotency_key=idempotency_key,
            payload=association.model_dump(mode="json"),
        )
