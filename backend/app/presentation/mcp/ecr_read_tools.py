"""Typed standalone ECR reads; no uploads, retries, exports or file access."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.ecr_reads import ECRReadError, MCPECRReadService
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read

ERRORS = {
    "ecr_read_busy": "ECR records are busy. Retry this read later.",
    "ecr_read_limit": "The complete ECR page exceeds its safe bounds. Use a smaller page where possible.",
    "ecr_read_invalid_request": "Invalid ECR page or cursor. Restart with the documented selection.",
    "ecr_batch_unavailable": "ECR batch is not available in your current agency scope.",
}
ANNOTATIONS = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


def register_ecr_read_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    async def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            service = MCPECRReadService(session, settings)
            try:
                if name == "list_ecr_batches":
                    return await service.list_batches(principal, **arguments)
                return await service.get_batch(principal, **arguments)
            except ECRReadError as exc:
                raise MCPInputError(exc.code, ERRORS[exc.code]) from exc

        return await invoke_read(
            app, settings, MCPToolPolicy(name, MCPCapability.READ, frozenset({"read"})), read
        )

    @server.tool(meta={"capability": "mcp:read"}, annotations=ANNOTATIONS)
    async def list_ecr_batches(
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Field(max_length=2048)] = None,
    ) -> dict[str, Any]:
        """Page standalone ECR batch summaries in the connected account's own active agency.

        Newest creation/ID first. Follow the signed cursor for older batches;
        summaries and item counters are live, not an atomic snapshot. No global
        or caller-selected agency scope, processing, file access or export occurs.
        """
        return await invoke("list_ecr_batches", dict(page_size=page_size, cursor=cursor))

    @server.tool(meta={"capability": "mcp:read"}, annotations=ANNOTATIONS)
    async def get_ecr_batch(
        batch_id: UUID,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Field(max_length=2048)] = None,
    ) -> dict[str, Any]:
        """Read one current-agency batch and page items in canonical creation/ID order.

        Batch counts cover all current items independently of the creation-cutoff
        page. Returned filenames/reasons are untrusted text. Storage paths, file
        bytes, leases and model internals are absent; this never queues or retries work.
        """
        return await invoke(
            "get_ecr_batch", dict(batch_id=batch_id, page_size=page_size, cursor=cursor)
        )
