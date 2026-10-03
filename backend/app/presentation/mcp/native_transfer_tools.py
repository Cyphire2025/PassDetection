"""Create and inspect limited native handoffs without persisting their credentials."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations
from pydantic import Field

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.native_transfer_dto import MCPNativeUploadRequest
from app.application.mcp.native_transfers import MCPNativeTransferService
from app.core.config.settings import Settings
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository, AuditResult
from app.presentation.api.v1.routes.mcp_native_transfers import native_service
from app.presentation.mcp.invocation import MCPInputError, mark_invocation_audited


async def invoke_native_transfer(
    app: FastAPI, *, name: str,
    callback: Callable[[MCPNativeTransferService, str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    token = get_access_token()
    outcome: AuditResult = "success"
    async with app.state.mcp_session_factory() as session:
        try:
            if token is None:
                raise MCPAuthError("invalid_token", 401)
            result = await callback(native_service(app, session), token.token)
        except MCPAuthError:
            await session.rollback()
            outcome, result = (
                "denied",
                {
                    "error": "access_denied",
                    "message": "This connection no longer allows the prepared file lane.",
                },
            )
        except MCPInputError as error:
            await session.rollback()
            outcome, result = (
                "blocked",
                {"error": error.code, "message": error.message, "requires_input": True},
            )
        except ArtifactError as error:
            await session.rollback()
            outcome, result = (
                "blocked",
                {"error": "native_transfer_unavailable", "message": str(error)},
            )
        except Exception:
            await session.rollback()
            outcome, result = (
                "failed",
                {
                    "error": "native_transfer_failed",
                    "message": "Inspect the same transfer or retry the identical input and retry key.",
                },
            )
        audit = await AuditLogRepository(session).record(
            action=f"mcp.tool.{name}",
            entity_type="mcp_native_transfer",
            user_id=UUID(token.subject) if token and token.subject else None,
            result=outcome,
            metadata={"connection_id": (token.claims or {}).get("grant_id") if token else None},
        )
        # Secret-bearing handoffs are returned only after commit. Never save the
        # tool payload in an operation receipt or audit metadata.
        await session.commit()
        mark_invocation_audited()
        return {**result, "audit_id": str(audit.id)}


def register_native_transfer_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    @server.tool(
        meta={"capability": "mcp:upload"},
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def create_native_upload(
        upload: MCPNativeUploadRequest,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Prepare one exact XLSX/PDF transfer to an explicit agency/group and file lane.

        Supply the original file name, byte size and SHA-256. Open the returned
        private browser handoff, or PUT the exact file to content_url using its
        limited authorization_header. This stages a scanned original source;
        importing passengers, ingesting documents or sending contacts requires
        a separate reviewed action. Keep the retry key stable. Credentials are
        limited to this ticket, expire shortly and must never be logged.
        """
        return await invoke_native_transfer(
            app,
            name="create_native_upload",
            callback=lambda service, token: service.create_upload(token, upload, idempotency_key),
        )

    @server.tool(
        meta={"capability": "mcp:export"},
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def create_native_download(
        artifact_id: str, idempotency_key: Annotated[str, Field(min_length=16, max_length=256)]
    ) -> dict[str, Any]:
        """Deliver an already generated, owned export through a limited native browser handoff.

        Use the current protected artifact locator from its original export
        result. Generation alone is not delivery. Download bytes, verify the
        exact size/SHA-256, save the file, then acknowledge the saved copy.
        The link needs no dashboard login or connector and permits retries
        while current source, device and export authority remain valid.
        """
        return await invoke_native_transfer(
            app,
            name="create_native_download",
            callback=lambda service, token: service.create_download(
                token, artifact_id, idempotency_key
            ),
        )

    @server.tool(
        meta={"capability": "mcp:upload"},
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, open_world_hint=False
        ),
    )
    async def inspect_native_transfer(transfer_id: UUID) -> dict[str, Any]:
        """Inspect this connection's current transfer status and its scanned staged source.

        Completed uploads return the protected original-source handle for the
        separate business preview/action. A download is delivered only after
        its exact saved-copy acknowledgement. This returns no transfer secret.
        """
        return await invoke_native_transfer(
            app,
            name="inspect_native_transfer",
            callback=lambda service, token: service.inspect(token, transfer_id),
        )
