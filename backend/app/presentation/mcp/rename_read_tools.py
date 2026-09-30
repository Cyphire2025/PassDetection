"""Metadata-only document-rename read tools with no file or mutation authority."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.rename_reads import MCPRenameReadService, RenameReadBusyError
from app.application.use_cases.document_rename.read_scope import DocumentRenameScopeError
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.repositories.document_rename_read_repository import (
    RenameReadLimitError,
    RenameReadUnavailableError,
)
from app.presentation.mcp.invocation import MCPInputError, invoke_read


def register_rename_read_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    async def dispatch(name: str, method: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            service = MCPRenameReadService(session, settings)
            methods: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {"list": service.list_batches, "get": service.get_batch}
            try:
                return await methods[method](principal, **arguments)
            except DocumentRenameScopeError as exc:
                raise MCPInputError("rename_scope_unavailable", "Your current account has no permitted agency scope for document rename.") from exc
            except RenameReadUnavailableError as exc:
                raise MCPInputError("rename_batch_unavailable", "The rename batch is unavailable in your current agency.") from exc
            except RenameReadLimitError as exc:
                raise MCPInputError("rename_read_limit", "The complete rename metadata observation exceeds supported item, field or response bounds. Try a smaller page when possible.") from exc
            except RenameReadBusyError as exc:
                raise MCPInputError("rename_read_busy", "Rename metadata is temporarily busy. Retry this same read shortly.") from exc
            except ValueError as exc:
                raise MCPInputError("invalid_rename_query", "Use a current batch ID, bounded page and unchanged cursor from this account's rename list.") from exc
        return await invoke_read(app, settings, MCPToolPolicy(name, MCPCapability.READ, frozenset({"read"})), read)

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def list_document_rename_batches(
        page_size: Annotated[int, Field(ge=1, le=100, strict=True)] = 100,
        cursor: Annotated[str | None, Field(max_length=2048)] = None,
    ) -> dict[str, Any]:
        """List authorized rename batches in this account's current agency; follow next_cursor.

        Titles may contain personal untrusted content. Live keyset pages include
        older retained batches. This never analyzes, renames, deletes or downloads.
        No user, agency or effective-role override is accepted.
        """
        return await dispatch("list_document_rename_batches", "list", {"page_size": page_size, "cursor": cursor})

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def get_document_rename_batch(
        batch_id: UUID, page: Annotated[int, Field(ge=1, le=1500, strict=True)] = 1,
        page_size: Annotated[int, Field(ge=1, le=100, strict=True)] = 100,
        include_extracted_identifiers: bool = False,
    ) -> dict[str, Any]:
        """Read filename-ordered item metadata for one batch from the current agency.

        Titles, filenames and reasons can contain personal information even when
        extracted identifiers are omitted. Opt in only when names/passport numbers/
        references are needed. Eligibility reflects stored metadata, never file
        existence or download authority. No file URLs, storage keys or contents.
        Pages are live; a batch above the canonical 1,500-file bound fails explicitly.
        """
        return await dispatch("get_document_rename_batch", "get", dict(batch_id=batch_id, page=page,
            page_size=page_size, include_extracted_identifiers=include_extracted_identifiers))
