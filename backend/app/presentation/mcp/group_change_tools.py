"""A narrow, typed creation tool; no update, link replacement or send behavior."""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import ConfigDict, Field, ValidationError, create_model

from app.application.dtos.client_group_dtos import CreateClientGroupInputDTO
from app.application.mcp.group_changes import MCPGroupCreationCommand, group_creation_operation
from app.core.config.settings import Settings
from app.presentation.api.v1.schemas.client_group_schemas import CreateClientGroupRequest
from app.presentation.mcp.invocation import MCPInputError, invoke_operation

# Keep the canonical field types without executing its cross-field validators
# in the SDK. Canonical validation runs inside the audited operation boundary,
# where failures return static messages instead of echoing submitted values.
GroupCreationFields = create_model(
    "GroupCreationFields",
    __config__=ConfigDict(extra="forbid", str_strip_whitespace=True),
    **{
        name: (field.annotation, deepcopy(field))
        for name, field in CreateClientGroupRequest.model_fields.items()
    },
)


class MCPCreateGroupRequest(GroupCreationFields):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agency_id: UUID
    owner_user_id: UUID
    collection_settings_confirmed: Literal[True] = Field(
        description="The user has chosen the collection fields, upload methods and custom questions. Ask before using defaults; do not enable every field automatically."
    )
    whatsapp_broadcast_group_ids: list[UUID] = Field(default_factory=list, max_length=0)
    matching_fields_by_broadcast: None = None


def validate_group_creation(payload: dict[str, Any]) -> MCPGroupCreationCommand:
    try:
        request = MCPCreateGroupRequest.model_validate(payload)
        shared = CreateClientGroupRequest.model_validate(
            request.model_dump(
                exclude={"agency_id", "owner_user_id", "collection_settings_confirmed"},
            )
        )
    except ValidationError as exc:
        # Pydantic error strings contain input values; return a static message.
        raise MCPInputError(
            "invalid_group_creation",
            "Provide valid group details, an IANA timezone, and a return date on or after departure. Only the documented creation fields are accepted.",
        ) from exc
    dto = CreateClientGroupInputDTO(
        **shared.model_dump(
            exclude={
                "whatsapp_broadcast_group_ids",
                "matching_fields_by_broadcast",
            }
        )
    )
    return MCPGroupCreationCommand(request.agency_id, request.owner_user_id, dto)


def register_group_change_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    definition = group_creation_operation(validate_group_creation)
    app.state.mcp_operations[definition.policy.name] = definition

    @server.tool(
        meta={"capability": "mcp:change"},
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def create_group(
        group: MCPCreateGroupRequest,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Create one new group for an explicit agency and eligible owner using website rules.

        Ask for missing or ambiguous agency/owner IDs, travel details, collection
        fields, accepted upload methods and custom questions. Explain the chosen
        options and obtain the user's choices before creation. Group
        names are not unique; this never edits or replaces an existing group.
        Reuse one stable idempotency key when retrying the same requested creation,
        including across connections. Changed details require a new intended
        operation, not silently a new key after an uncertain response. No people,
        broadcast links or messages are created. The secure upload token is not
        returned; open the returned application group link to manage collection.
        """
        return await invoke_operation(
            app,
            settings,
            definition,
            idempotency_key=idempotency_key,
            payload=group.model_dump(mode="json"),
        )
