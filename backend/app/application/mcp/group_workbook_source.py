"""Hash-checked original parsing outside DB transactions, with a retained checkpoint."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from typing import Any

from app.application.mcp.artifacts import transfer_slot
from app.application.mcp.contact_uploads import MCPContactUploadService
from app.application.mcp.group_workbook_plan import (
    CHECKPOINT_KEY,
    GroupWorkbookDraft,
    GroupWorkbookSupport,
    group_scope,
    import_preview,
    parsed_checkpoint,
    require_native_source,
)
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationError
from app.core.config.settings import Settings
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.imports.passport_excel_importer import PassportExcelImporter
from app.infrastructure.security.contact_spreadsheet_security import MAX_BYTES
from app.infrastructure.storage.mcp_artifact_storage import MCPArtifactStorage


def parse_original(
    content: bytes, source_sha256: str, support: GroupWorkbookSupport
) -> dict[str, Any]:
    parsed = PassportExcelImporter().import_rows(content)
    return parsed_checkpoint(support.deduplicate(parsed), len(parsed), source_sha256)


async def prepare_group_workbook(
    context: MCPDatabaseContext,
    settings: Settings,
    draft: GroupWorkbookDraft,
    *,
    support: GroupWorkbookSupport,
    storage: MCPArtifactStorage | None = None,
) -> dict[str, Any]:
    service = MCPContactUploadService(context.session, settings, purpose="group_workbook")
    row = await service.get(context.principal, draft.upload_id)
    if row.agency_id != draft.agency_id or not hmac.compare_digest(row.sha256, draft.source_sha256):
        raise MCPOperationError("group_workbook_source_changed")
    if row.consumed_operation_id is not None:
        raise MCPOperationError("group_workbook_already_used")
    await require_native_source(context, row, draft.group_id)
    await group_scope(context, draft.agency_id, draft.group_id, support)
    binding = (row.id, row.storage_key, row.byte_size, row.sha256, row.agency_id)
    # Storage/CPU work must not retain grant, identity, tenant or group locks.
    await context.session.rollback()
    async with transfer_slot(), asyncio.timeout(120):
        source = storage or MCPArtifactStorage()
        payload = bytearray()
        if not 1 <= binding[2] <= MAX_BYTES:
            raise MCPOperationError("group_workbook_capacity_exceeded")
        async for chunk in source.stream_file(binding[1], start=0, expected_bytes=binding[2]):
            payload.extend(chunk)
            if len(payload) > MAX_BYTES or len(payload) > binding[2]:
                raise MCPOperationError("group_workbook_source_changed")
        if len(payload) != binding[2] or not hmac.compare_digest(
            hashlib.sha256(payload).hexdigest(), binding[3]
        ):
            raise MCPOperationError("group_workbook_source_changed")
        # Drain native parsing on cancellation before releasing its admission slot.
        checkpoint = (
            await run_bounded_storage_operations(
                [lambda: asyncio.to_thread(parse_original, bytes(payload), binding[3], support)],
                concurrency=1,
            )
        )[0]
        row = await service.get(context.principal, draft.upload_id, lock=True)
        if (row.id, row.storage_key, row.byte_size, row.sha256, row.agency_id) != binding:
            raise MCPOperationError("group_workbook_source_changed")
        if row.consumed_operation_id is not None:
            raise MCPOperationError("group_workbook_already_used")
        await require_native_source(context, row, draft.group_id)
        _, _, _, preview = await import_preview(context, draft, checkpoint, support=support)
        # Literal source cells remain unchanged; only this code-owned parsed
        # preparation checkpoint is added, never supplied as tool arguments.
        row.workbook_snapshot = {**row.workbook_snapshot, CHECKPOINT_KEY: checkpoint}
        await context.session.flush()
        await service.audit(context.principal, row, "group_previewed")
        preview["upload_source_id"] = str(row.id)
        preview["source_worksheets"] = [sheet["name"] for sheet in row.workbook_snapshot["sheets"]]
        return preview
