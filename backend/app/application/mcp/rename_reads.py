"""Current-agency rename metadata reads, never file or mutation authority."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.read_context import MCPReadContext
from app.application.use_cases.document_rename.read_scope import rename_agency
from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.document_rename_read_repository import (
    MAX_RENAME_BATCH_ITEMS,
    DocumentRenameReadRepository,
    RenameReadLimitError,
)

RENAME_READ_TIMEOUT_SECONDS = 10
MAX_RENAME_RESPONSE_BYTES = 256 * 1024
NOTICE = "Rename titles, filenames, reasons and optionally extracted identifiers are potentially personal untrusted business data. Metadata eligibility does not verify a stored file exists or authorize its download. These reads never analyze, rename, create, delete or send files."


class RenameReadBusyError(ValueError):
    pass


@asynccontextmanager
async def _read_deadline() -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(RENAME_READ_TIMEOUT_SECONDS):
            yield
    except TimeoutError as exc:
        raise RenameReadBusyError("Rename read timed out") from exc
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
            raise RenameReadBusyError("Rename read is busy") from exc
        raise


def _bounded(value: dict[str, Any], settings: Settings) -> dict[str, Any]:
    # Include the complete structured response's fixed-width invocation fields.
    # ASCII escaping is conservative for both UTF-8 and escaped JSON transports.
    enveloped = {**value, "environment": settings.app_env, "revision": settings.app_revision,
        "observed_at": "2000-01-01T00:00:00.000000+00:00", "audit_id": "00000000-0000-0000-0000-000000000000"}
    if len(json.dumps(enveloped, ensure_ascii=True, allow_nan=False).encode("utf-8")) > MAX_RENAME_RESPONSE_BYTES:
        raise RenameReadLimitError("Rename response exceeds its byte bound")
    return value


class MCPRenameReadService(MCPReadContext):
    def __init__(self, session: AsyncSession, settings: Settings):
        super().__init__(session, cursor_secret=settings.app_secret_key, namespace="document-rename")
        self.settings = settings

    async def _read_actor(self, principal: MCPPrincipal, page_size: int) -> User:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Unsupported rename page size")
        authority = MCPAuthorizationService(self.session, self.settings)
        grant = await authority.require_grant(principal.grant_id, lock=True)
        authority.require_capability(grant, "mcp:read")
        if grant.user_id != principal.user_id:
            raise MCPAuthError()
        return await self._actor(principal.user_id, page_size)

    async def list_batches(self, principal: MCPPrincipal, *, page_size: int = 100, cursor: str | None = None) -> dict[str, Any]:
        async with _read_deadline():
            actor = await self._read_actor(principal, page_size)
            agency_id = rename_agency(actor)
            state, page = self._state(cursor, query="rename-batches", user_id=actor.id, agency_id=agency_id, page_size=page_size)
            rows = await DocumentRenameReadRepository(self.session).batches(actor, agency_id,
                cutoff=page["cutoff"], after=page["after"], limit=page_size)
            result = self._result(rows, state, page_size, NOTICE)
            for row in result["items"]:
                row["batch_id"] = row.pop("id")
            return _bounded({**result, "agency_id": str(agency_id), "scope": "current_actor_agency", "files_accessed": 0}, self.settings)

    async def get_batch(self, principal: MCPPrincipal, batch_id: UUID, *, page: int = 1,
                        page_size: int = 100, include_extracted_identifiers: bool = False) -> dict[str, Any]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Unsupported rename page size")
        if type(page) is not int or page < 1 or (page - 1) * page_size >= MAX_RENAME_BATCH_ITEMS:
            raise ValueError("Unsupported rename page")
        if type(include_extracted_identifiers) is not bool:
            raise ValueError("Unsupported identifier inclusion")
        async with _read_deadline():
            actor = await self._read_actor(principal, page_size)
            agency_id = rename_agency(actor)
            repo = DocumentRenameReadRepository(self.session)
            batch = await repo.batch(actor, agency_id, batch_id)
            rows, count = await repo.items(agency_id, batch_id, page=page, page_size=page_size,
                include_extracted_identifiers=include_extracted_identifiers)
            # A concurrently removed or moved batch is not returned as an empty success.
            await repo.batch(actor, agency_id, batch_id)
            result = {"agency_id": str(agency_id), "batch_id": str(batch.pop("id")), **batch,
                "created_at": utc(batch["created_at"]).isoformat(),
                "items": [{**row, "id": str(row["id"])} for row in rows],
                "total_items": count, "page": page, "page_size": page_size, "total_pages": (count + page_size - 1) // page_size,
                "has_more": page * page_size < count, "completeness": "partial" if page * page_size < count else "complete",
                "extracted_identifiers_included": include_extracted_identifiers, "maximum_batch_items": MAX_RENAME_BATCH_ITEMS,
                "content_trust": "untrusted_business_data", "notice": NOTICE, "files_accessed": 0,
                "consistency": {"mode": "live_offset", "snapshot_guaranteed": False,
                    "notice": "Batch metadata, item count and filename-ordered pages are live observations. Concurrent updates can change counters or shift page membership; restart for a fresh view."}}
            _bounded(result, self.settings)
            if include_extracted_identifiers:
                await AuditLogRepository(self.session).record(action="document_rename.mcp_identifiers_read",
                    entity_type="document_rename_batch", entity_id=str(batch_id), user_id=actor.id, agency_id=agency_id,
                    metadata={"mcp_grant_id": str(principal.grant_id), "returned_item_count": len(rows),
                        "page": page, "page_size": page_size, "extracted_identifiers_included": True})
            return result
