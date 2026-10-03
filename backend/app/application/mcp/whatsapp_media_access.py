"""Scoped header-image locators and explicit ready-only recovery across grants."""

from __future__ import annotations

import base64
import hmac
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, credential_hash, utc
from app.application.mcp.permissions import require_tool_access
from app.core.config.settings import Settings
from app.infrastructure.database.mcp_whatsapp_media_models import (
    MCPWhatsAppHeaderAccessModel,
    MCPWhatsAppHeaderMediaModel,
)
from app.infrastructure.database.models import AgencyModel, WhatsAppBroadcastGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

MEDIA_HANDLE = re.compile(r"gcmcp_wa_media_[A-Za-z0-9_-]{64}\Z")


class MCPWhatsAppMediaAccess:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings
        self.authorization = MCPAuthorizationService(session, settings)

    async def authority(self, principal: MCPPrincipal, *, lock: bool = False) -> None:
        grant = await self.authorization.require_grant(principal.grant_id, lock=lock)
        if (
            utc(principal.expires_at) <= datetime.now(UTC)
            or grant.user_id != principal.user_id
            or grant.client_id != principal.client_id
            or grant.resource != principal.resource
        ):
            raise MCPAuthError("invalid_token", 401)
        for capability in ("mcp:upload", "mcp:communicate"):
            self.authorization.require_capability(grant, capability)
            await require_tool_access(
                self.session, self.settings, grant.id, "upload_whatsapp_header", capability,
                lock=lock,
            )

    async def scope(
        self, agency_id: uuid.UUID, broadcast_id: uuid.UUID, *, lock: bool = False
    ) -> None:
        agency_stmt = select(AgencyModel).where(AgencyModel.id == agency_id)
        broadcast_stmt = select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == broadcast_id,
            WhatsAppBroadcastGroupModel.agency_id == agency_id,
        )
        if lock:
            agency_stmt, broadcast_stmt = (
                agency_stmt.with_for_update(read=True),
                broadcast_stmt.with_for_update(),
            )
        agency = await self.session.scalar(agency_stmt.execution_options(populate_existing=True))
        broadcast = await self.session.scalar(
            broadcast_stmt.execution_options(populate_existing=True)
        )
        if (
            agency is None
            or not agency.is_active
            or broadcast is None
            or broadcast.archived_at is not None
        ):
            raise MCPAuthError("access_denied", 403)

    def handle(self, row: MCPWhatsAppHeaderMediaModel, grant_id: uuid.UUID) -> str:
        message = f"gc-mcp-wa-media-v1\0{row.id}\0{row.user_id}\0{grant_id}".encode()
        return "gcmcp_wa_media_" + base64.urlsafe_b64encode(
            hmac.digest(self.settings.app_secret_key.encode(), message, "sha384")
        ).decode().rstrip("=")

    async def get(
        self,
        principal: MCPPrincipal,
        handle: str,
        *,
        lock: bool = False,
    ) -> MCPWhatsAppHeaderMediaModel:
        await self.authority(principal, lock=lock)
        if not MEDIA_HANDLE.fullmatch(handle):
            raise ArtifactError("Header image was not found", 404)
        stmt = (
            select(MCPWhatsAppHeaderMediaModel)
            .join(
                MCPWhatsAppHeaderAccessModel,
                MCPWhatsAppHeaderAccessModel.media_id == MCPWhatsAppHeaderMediaModel.id,
            )
            .where(
                MCPWhatsAppHeaderMediaModel.user_id == principal.user_id,
                MCPWhatsAppHeaderAccessModel.grant_id == principal.grant_id,
                MCPWhatsAppHeaderAccessModel.handle_hash
                == credential_hash(handle, self.settings.app_secret_key),
            )
        )
        row = await self.session.scalar(stmt.execution_options(populate_existing=True))
        if row is None or utc(row.expires_at) <= datetime.now(UTC):
            raise ArtifactError("Header image was not found", 404)
        await self.scope(row.agency_id, row.broadcast_id, lock=lock)
        if lock:
            row = await self.session.scalar(
                stmt.with_for_update(of=MCPWhatsAppHeaderMediaModel).execution_options(
                    populate_existing=True
                )
            )
            if row is None or utc(row.expires_at) <= datetime.now(UTC):
                raise ArtifactError("Header image was not found", 404)
        return row

    async def recover(self, principal: MCPPrincipal, identifier: uuid.UUID) -> dict[str, Any]:
        await self.authority(principal, lock=True)
        row = await self.session.scalar(
            select(MCPWhatsAppHeaderMediaModel).where(
                MCPWhatsAppHeaderMediaModel.id == identifier,
                MCPWhatsAppHeaderMediaModel.user_id == principal.user_id,
            )
        )
        if row is None:
            raise ArtifactError("Header image was not found", 404)
        await self.scope(row.agency_id, row.broadcast_id, lock=True)
        row = await self.session.scalar(
            select(MCPWhatsAppHeaderMediaModel)
            .where(
                MCPWhatsAppHeaderMediaModel.id == identifier,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.status != "ready" or utc(row.expires_at) <= datetime.now(UTC):
            raise ArtifactError("Only an unexpired ready image can be recovered", 409)
        if row.provider_phone_number_id != self.settings.whatsapp_phone_number_id:
            raise ArtifactError("Header image belongs to another sender configuration", 409)
        handle = self.handle(row, principal.grant_id)
        existing = await self.session.get(
            MCPWhatsAppHeaderAccessModel, (row.id, principal.grant_id)
        )
        if existing is None:
            self.session.add(
                MCPWhatsAppHeaderAccessModel(
                    media_id=row.id,
                    grant_id=principal.grant_id,
                    handle_hash=credential_hash(handle, self.settings.app_secret_key),
                )
            )
            await self.audit(principal, row, "recovered")
            await self.session.flush()
        return self.metadata(row, handle)

    async def observe(self, principal: MCPPrincipal, handle: str) -> dict[str, Any]:
        row = await self.get(principal, handle, lock=True)
        now = datetime.now(UTC)
        # A live provider attempt holds this row lock. Only an expired durable
        # claim left after that owner exits can become an uncertain observation.
        if (
            row.status == "uploading"
            and row.attempt_id is not None
            and row.attempt_expires_at is not None
            and utc(row.attempt_expires_at) <= now
        ):
            row.status, row.failure_code = "unknown", "provider_upload_receipt_unavailable"
            row.updated_at, row.completed_at = now, now
            row.revision += 1
            await self.audit(principal, row, "unknown")
        return self.metadata(row, handle)

    @staticmethod
    def metadata(row: MCPWhatsAppHeaderMediaModel, handle: str) -> dict[str, Any]:
        return {
            "media_artifact_id": str(row.id),
            "media_handle": handle,
            "agency_id": str(row.agency_id),
            "broadcast_id": str(row.broadcast_id),
            "filename": row.filename,
            "media_type": row.original_media_type,
            "byte_size": row.original_byte_size,
            "sha256": row.original_sha256,
            "provider_content_sha256": row.normalized_sha256,
            "status": row.status,
            "expires_at": utc(row.expires_at).isoformat(),
            "attempt_deadline": utc(row.attempt_expires_at).isoformat()
            if row.attempt_expires_at
            else None,
            "failure_code": row.failure_code,
            "revision": row.revision,
            "messages_queued": 0,
        }

    async def audit(
        self, principal: MCPPrincipal, row: MCPWhatsAppHeaderMediaModel, action: str
    ) -> None:
        await AuditLogRepository(self.session).record(
            action=f"mcp.whatsapp_header_{action}",
            entity_type="mcp_whatsapp_header_media",
            entity_id=str(row.id),
            agency_id=row.agency_id,
            user_id=principal.user_id,
            metadata={
                "grant_id": str(principal.grant_id),
                "broadcast_id": str(row.broadcast_id),
                "status": row.status,
            },
        )
