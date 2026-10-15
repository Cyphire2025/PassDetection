"""Typed business accounts and canonical, revision-fenced GC App settings."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationError,
    field_validator,
)

from app.application.mcp.access_changes import require_access_mfa
from app.application.mcp.account_creation import (
    ClientManagerCreationSupport,
    authorize_account_receipt,
    create_client_manager,
    create_workforce,
)
from app.application.mcp.change_context import require_change_actor, require_change_group
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.core.config.settings import Settings
from app.core.security.mobile_jwt import hash_mobile_lookup
from app.domain.entities.entities import User
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.api.v1.routes import gc_app, gc_app_content
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupAccessUpdateRequest,
    GCMyPhotosFeatureUpdateRequest,
)
from app.presentation.mcp.invocation import MCPInputError, invoke_operation


class MCPWorkforceAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID = Field(
        description="The creating administrator's current active agency; inspect it first."
    )
    account_type: Literal["coordinator", "staff", "manager"]
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    credential_delivery: Literal["dashboard_activation"] = Field(
        description="Explicitly acknowledge a separate dashboard activation/reset handoff. No invitation is sent."
    )


class MCPClientManagerAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    organization_id: UUID = Field(
        description="An existing active client organization in the selected agency."
    )
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    phone_number: str = Field(
        min_length=8,
        max_length=64,
        description="Explicit mobile number including country code, used by canonical mobile identity matching.",
    )
    group_ids: list[UUID] = Field(
        default_factory=list,
        max_length=100,
        description="Explicit GC groups owned by this organization; empty means no initial group access.",
    )
    credential_delivery: Literal["dashboard_activation"]

    @field_validator("group_ids")
    @classmethod
    def distinct_groups(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("Select distinct group IDs")
        return values


class MCPGCGroupSettings(GCGroupAccessUpdateRequest):
    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    group_id: UUID
    passenger_access_enabled: bool
    client_manager_access_enabled: bool
    coordinator_access_enabled: bool
    client_organization_id: UUID
    expected_revision: int | None = Field(default=None, ge=1, strict=True)
    access_starts_at: AwareDatetime | None = Field(
        default=None, description="Optional inclusive access start with explicit timezone offset."
    )
    access_expires_at: AwareDatetime | None = Field(
        default=None, description="Optional access expiry with timezone offset; later than start."
    )


class MCPGCMyPhotos(GCMyPhotosFeatureUpdateRequest):
    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    group_id: UUID
    expected_revision: int = Field(ge=1, strict=True)


class MCPPublishItinerary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    group_id: UUID
    version_id: UUID = Field(
        description="Existing draft itinerary version to publish; previous published versions remain as retired history."
    )
    expected_access_revision: int = Field(ge=1, strict=True)


BUSINESS_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "create_workforce_account": MCPWorkforceAccount,
    "create_gc_client_manager_account": MCPClientManagerAccount,
    "configure_gc_group_access": MCPGCGroupSettings,
    "configure_gc_my_photos": MCPGCMyPhotos,
    "publish_gc_itinerary": MCPPublishItinerary,
}


def workforce_permission_sections(data: dict[str, Any]) -> frozenset[str]:
    role = data.get("account_type")
    section = (
        {"coordinator": "coordinators", "staff": "staff", "manager": "manager"}.get(role)
        if type(role) is str
        else None
    )
    if section is None:
        raise MCPInputError(
            "invalid_business_configuration", "Select coordinator, staff or manager explicitly."
        )
    return frozenset({section})


def validate_business(kind: str, payload: dict[str, Any]) -> BaseModel:
    try:
        return BUSINESS_TOOL_MODELS[kind].model_validate(payload)
    except ValidationError as exc:
        raise MCPInputError(
            "invalid_business_configuration",
            "Provide the documented required fields and explicit IDs. Passwords, credential tokens and extra fields are not accepted.",
        ) from exc


def _request() -> Request:
    # There is no browser authority in this synthetic context: actor and tenant
    # come from the operation grant, and only canonical audit helpers use it.
    return Request({"type": "http", "headers": [], "client": None})


async def _gc_scope(context: MCPDatabaseContext, agency_id: UUID, group_id: UUID) -> User:
    actor = await require_change_actor(context, agency_id)
    await require_access_mfa(context)
    await require_change_group(context, actor, group_id, agency_id, exclusive=True)
    return actor


def business_definition(kind: str) -> MCPDatabaseOperation:
    if kind not in BUSINESS_TOOL_MODELS:
        raise ValueError("Unsupported business administration operation")

    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        body = validate_business(kind, payload)
        try:
            if isinstance(body, MCPWorkforceAccount):
                return await create_workforce(context, body)
            if isinstance(body, MCPClientManagerAccount):
                support = ClientManagerCreationSupport(
                    gc_app._get_organization,
                    gc_app._validate_manager_groups,
                    normalize_whatsapp_phone,
                    hash_mobile_lookup,
                )
                return await create_client_manager(context, body, support)
            assert isinstance(body, (MCPGCGroupSettings, MCPGCMyPhotos, MCPPublishItinerary))
            response: BaseModel
            actor = await _gc_scope(context, body.agency_id, body.group_id)
            if isinstance(body, MCPGCGroupSettings):
                settings_body = GCGroupAccessUpdateRequest.model_validate(
                    body.model_dump(exclude={"agency_id", "group_id"})
                )
                response = await gc_app.configure_gc_group_access(
                    body.group_id,
                    settings_body,
                    _request(),
                    agency_id=body.agency_id,
                    current_user=actor,
                    session=context.session,
                )
            elif isinstance(body, MCPGCMyPhotos):
                photos_body = GCMyPhotosFeatureUpdateRequest(
                    enabled=body.enabled, expected_revision=body.expected_revision
                )
                response = await gc_app.configure_gc_group_my_photos_feature(
                    body.group_id,
                    photos_body,
                    _request(),
                    agency_id=body.agency_id,
                    current_user=actor,
                    session=context.session,
                )
            else:
                access, _ = await gc_app_content._admin_access_context(
                    context.session, actor, body.group_id, agency_id=body.agency_id, lock=True
                )
                gc_app_content._require_access_revision(access, body.expected_access_revision)
                response = await gc_app_content.publish_itinerary(
                    body.group_id,
                    body.version_id,
                    _request(),
                    agency_id=body.agency_id,
                    current_user=actor,
                    session=context.session,
                )
            return MCPDatabaseResult(
                {
                    "agency_id": str(body.agency_id),
                    "group_id": str(body.group_id),
                    "configuration": response.model_dump(mode="json", exclude={"days"}),
                    "history_retained": True,
                }
            )
        except HTTPException as exc:
            raise MCPInputError(
                "business_configuration_conflict"
                if exc.status_code == 409
                else "business_configuration_unavailable",
                "The account, organization, group, revision or publication is unavailable under current application rules. Inspect current records and resolve required fields before a new intended operation.",
            ) from exc
        except MCPOperationError as exc:
            raise MCPInputError(
                exc.code,
                "Current account scope, identity or recent MFA does not allow this operation. Inspect the agency and account, or authorize a fresh connection with MFA. No credentials were disclosed.",
            ) from exc

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        if kind.startswith("create_"):
            await authorize_account_receipt(context, receipt)
        else:
            data = receipt["data"]
            await _gc_scope(context, UUID(data["agency_id"]), UUID(data["group_id"]))

    effects = (
        {"create", "audit"}
        if kind.startswith("create_")
        else {"change_business_settings", "retain_history", "audit"}
    )
    return MCPDatabaseOperation(
        MCPToolPolicy(kind, MCPCapability.CHANGE, frozenset(effects)),
        mutate,
        authorize,
        permission_sections=workforce_permission_sections
        if kind == "create_workforce_account"
        else None,
    )


def register_business_admin_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    definitions = {name: business_definition(name) for name in BUSINESS_TOOL_MODELS}
    app.state.mcp_operations.update(definitions)
    annotations = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def create_workforce_account(
        account: MCPWorkforceAccount,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Create an invited coordinator, staff or manager in the administrator's own agency.

        Ask for full name, email, role and dashboard activation acknowledgement.
        No password/activation secret enters MCP, no invitation is sent and no
        group assignment is implicit. Finish credential delivery in the dashboard.
        Reuse the exact input and stable key after an uncertain response.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["create_workforce_account"],
            idempotency_key=idempotency_key,
            payload=account.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def create_gc_client_manager_account(
        account: MCPClientManagerAccount,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Create an invited external client manager for an existing organization and explicit GC groups.

        Ask for name, email, international mobile number, agency, organization,
        selected group IDs and dashboard activation acknowledgement. Initial group
        access excludes passenger names and personal documents. No credential or
        provider invitation is returned/sent; obtain a fresh link in the dashboard.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["create_gc_client_manager_account"],
            idempotency_key=idempotency_key,
            payload=account.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def configure_gc_group_access(
        configuration: MCPGCGroupSettings,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Add or change GC App group publication/access settings using canonical rules.

        Inspect the group/access revision and organization first. Ask explicitly
        whether global, passenger, client-manager and coordinator access should be
        enabled, and for the optional aware start/expiry window. Existing access
        requires its exact expected_revision; omitted revision is for new access.
        Disabling roles or narrowing windows revokes affected mobile sessions and
        advances synchronization history. It preserves all records and audits.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["configure_gc_group_access"],
            idempotency_key=idempotency_key,
            payload=configuration.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def configure_gc_my_photos(
        configuration: MCPGCMyPhotos,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Change the GC App passenger My Photos feature using its freshly inspected access revision."""
        return await invoke_operation(
            app,
            settings,
            definitions["configure_gc_my_photos"],
            idempotency_key=idempotency_key,
            payload=configuration.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def publish_gc_itinerary(
        publication: MCPPublishItinerary,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Publish an existing GC itinerary draft using current group/access revision.

        Resolve exact agency/group/draft IDs and inspect the access revision first.
        Previous publications are retained as retired versions; mobile sync history
        advances. No notification, passenger attendance or source deletion occurs.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["publish_gc_itinerary"],
            idempotency_key=idempotency_key,
            payload=publication.model_dump(mode="json"),
        )
