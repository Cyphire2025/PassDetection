"""Fixed, agency-scoped contact workbook staging; no business creation or sends."""

from __future__ import annotations

import asyncio
import base64
import hmac
import re
import tempfile
import uuid
from collections.abc import AsyncIterable
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError, _filename, _spool, transfer_slot
from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, credential_hash, utc
from app.core.config.settings import Settings
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.models import AgencyModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.contact_spreadsheet_security import (
    MAX_BYTES,
    XLSX_MEDIA,
    ContactSpreadsheetSecurity,
)
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.infrastructure.storage.mcp_artifact_storage import MCPArtifactStorage

HANDLE = re.compile(r"gcmcp_contacts_[A-Za-z0-9_-]{64}\Z")


class MCPContactUploadService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        storage: MCPArtifactStorage | None = None,
        security: ContactSpreadsheetSecurity | None = None,
    ):
        self.session, self.settings = session, settings
        self.storage, self.security = storage, security
        self.auth = MCPAuthorizationService(session, settings)

    async def authority(self, principal: MCPPrincipal, *, lock: bool = False) -> None:
        grant = await self.auth.require_grant(principal.grant_id, lock=lock)
        if (
            utc(principal.expires_at) <= datetime.now(UTC)
            or grant.user_id != principal.user_id
            or grant.client_id != principal.client_id
            or grant.resource != principal.resource
        ):
            raise MCPAuthError("invalid_token", 401)
        self.auth.require_capability(grant, "mcp:upload")

    async def agency(self, agency_id: uuid.UUID, *, lock: bool = False) -> None:
        stmt = select(AgencyModel).where(AgencyModel.id == agency_id)
        if lock:
            stmt = stmt.with_for_update(read=True)
        row = await self.session.scalar(stmt.execution_options(populate_existing=True))
        if row is None or not row.is_active:
            raise MCPAuthError("access_denied", 403)

    async def stage(
        self,
        principal: MCPPrincipal,
        *,
        agency_id: uuid.UUID,
        filename: str,
        expected_size: int,
        expected_sha256: str,
        body: AsyncIterable[bytes],
    ) -> dict[str, Any]:
        if (
            not 1 <= expected_size <= MAX_BYTES
            or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None
        ):
            raise ArtifactError("Provide a valid workbook size and SHA-256", 422)
        if not filename.lower().endswith(".xlsx"):
            raise ArtifactError("This upload lane accepts .xlsx files only", 415)
        await self.authority(principal)
        await self.agency(agency_id)
        # Parsing/scanning must not retain an application transaction or agency lock.
        await self.session.rollback()
        async with transfer_slot(), asyncio.timeout(120):
            with tempfile.TemporaryFile(mode="w+b") as temporary:
                staged = cast(BinaryIO, temporary)
                size, checksum = await _spool(body, staged, maximum=MAX_BYTES)
                if size != expected_size or not hmac.compare_digest(checksum, expected_sha256):
                    raise ArtifactError("Workbook size or SHA-256 does not match", 422)
                staged.seek(0)
                security = self.security or ContactSpreadsheetSecurity(settings=self.settings)
                snapshot = await security.validate_spreadsheet(
                    content=staged.read(MAX_BYTES + 1),
                    context=UploadSecurityContext(
                        ingestion_flow="mcp_contact_excel",
                        agency_id=agency_id,
                        user_id=principal.user_id,
                    ),
                )
                await self.authority(principal, lock=True)
                await self.agency(agency_id, lock=True)
                identifier, now = uuid.uuid4(), datetime.now(UTC)
                message = f"gc-mcp-contacts-v1\0{identifier}\0{principal.user_id}\0{principal.grant_id}".encode()
                handle = "gcmcp_contacts_" + base64.urlsafe_b64encode(
                    hmac.digest(self.settings.app_secret_key.encode(), message, "sha384")
                ).decode().rstrip("=")
                row = MCPContactImportUploadModel(
                    id=identifier,
                    user_id=principal.user_id,
                    original_grant_id=principal.grant_id,
                    agency_id=agency_id,
                    handle_hash=credential_hash(handle, self.settings.app_secret_key),
                    storage_key=f"mcp-transfers/v1/{identifier}",
                    filename=_filename(filename, ".xlsx"),
                    media_type=XLSX_MEDIA,
                    byte_size=size,
                    sha256=checksum,
                    workbook_snapshot=snapshot,
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                )
                storage = self.storage or MCPArtifactStorage()
                await storage.put_transfer(
                    staged,
                    key=row.storage_key,
                    size=size,
                    sha256=checksum,
                    media_type=XLSX_MEDIA,
                )
                self.session.add(row)
                await self.session.flush()
                await self.audit(principal, row, "staged")
                return self.metadata(row, handle)

    async def get(
        self,
        principal: MCPPrincipal,
        handle: str,
        *,
        lock: bool = False,
    ) -> MCPContactImportUploadModel:
        await self.authority(principal)
        if not HANDLE.fullmatch(handle):
            raise ArtifactError("Contact workbook was not found", 404)
        stmt = (
            select(MCPContactImportUploadModel)
            .where(
                MCPContactImportUploadModel.handle_hash
                == credential_hash(handle, self.settings.app_secret_key),
                MCPContactImportUploadModel.user_id == principal.user_id,
                MCPContactImportUploadModel.original_grant_id == principal.grant_id,
            )
            .execution_options(populate_existing=True)
        )
        row = await self.session.scalar(stmt)
        if row is None or utc(row.expires_at) <= datetime.now(UTC):
            raise ArtifactError("Contact workbook was not found", 404)
        await self.agency(row.agency_id, lock=lock)
        if lock:
            row = await self.session.scalar(stmt.with_for_update())
            if row is None or utc(row.expires_at) <= datetime.now(UTC):
                raise ArtifactError("Contact workbook was not found", 404)
        return row

    async def audit(
        self, principal: MCPPrincipal, row: MCPContactImportUploadModel, action: str
    ) -> None:
        await AuditLogRepository(self.session).record(
            action=f"mcp.contact_upload_{action}",
            entity_type="mcp_contact_upload",
            entity_id=str(row.id),
            agency_id=row.agency_id,
            user_id=principal.user_id,
            metadata={"grant_id": str(principal.grant_id), "byte_size": row.byte_size},
        )

    @staticmethod
    def metadata(row: MCPContactImportUploadModel, handle: str) -> dict[str, Any]:
        return {
            "upload_id": handle,
            "agency_id": str(row.agency_id),
            "filename": row.filename,
            "media_type": row.media_type,
            "byte_size": row.byte_size,
            "sha256": row.sha256,
            "expires_at": utc(row.expires_at).isoformat(),
            "business_import": "not_started",
            "worksheets": [
                {
                    "name": sheet["name"],
                    "row_count": len(sheet["rows"]),
                    "column_count": max((len(row) for row in sheet["rows"]), default=0),
                }
                for sheet in row.workbook_snapshot["sheets"]
            ],
        }
