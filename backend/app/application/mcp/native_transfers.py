"""Short-lived native handoff authority, independent of ambient browser sessions."""

import base64
import hashlib
import hmac
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService, _filename
from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.contact_uploads import MCPContactUploadService
from app.application.mcp.credentials import MCPAuthError, credential_hash, utc
from app.application.mcp.native_transfer_dto import MCPNativeUploadRequest
from app.application.mcp.operations import MCPOperationService
from app.application.mcp.permissions import require_tool_access
from app.core.config.settings import Settings
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.mcp_native_transfer_models import MCPNativeTransferModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.contact_spreadsheet_security import MAX_BYTES, XLSX_MEDIA

TOKEN = re.compile(r"gcmcp_transfer_[A-Za-z0-9_-]{64}\Z")
TTL = timedelta(minutes=10)
MAX_NATIVE_DOWNLOAD_BYTES = 128 * 1024 * 1024
_SECTIONS = {
    "contact_broadcast": "whatsapp_broadcasts",
    "group_workbook": "group_excel_imports",
    "document_pdf": "document_delivery",
    "export": "exports",
}
_EXPORT_TOOLS = {
    "passport_excel": "prepare_excel_export",
    "passport_images": "prepare_image_export",
    "whatsapp_tracking_excel": "prepare_tracking_export",
    "rooming_list_excel": "prepare_rooming_export",
    "rooming_checkins_excel": "prepare_rooming_export",
    "document_assignments_excel": "prepare_document_assignment_export",
}


class MCPNativeTransferService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        artifacts: MCPArtifactService | None = None,
        contact_storage=None,
        contact_security=None,
    ):
        self.session, self.settings = session, settings
        self.auth = MCPAuthorizationService(session, settings)
        self.artifacts = artifacts or MCPArtifactService(session, settings)
        self.contact_storage, self.contact_security = contact_storage, contact_security

    def token(self, row: MCPNativeTransferModel) -> str:
        binding = f"gc-native-transfer-v1\0{row.id}\0{row.original_grant_id}\0{row.user_id}\0{row.payload_hash}".encode()
        return "gcmcp_transfer_" + base64.urlsafe_b64encode(
            hmac.digest(self.settings.app_secret_key.encode(), binding, "sha384")
        ).decode().rstrip("=")

    def contact_service(self, purpose: str) -> MCPContactUploadService:
        return MCPContactUploadService(
            self.session,
            self.settings,
            storage=self.contact_storage,
            security=self.contact_security,
            purpose=purpose,
        )

    async def audit(self, row: MCPNativeTransferModel, action: str) -> None:
        await AuditLogRepository(self.session).record(
            action=f"mcp.native_transfer_{action}",
            entity_type="mcp_native_transfer",
            entity_id=str(row.id),
            user_id=row.user_id,
            agency_id=row.agency_id,
            metadata={
                "grant_id": str(row.original_grant_id),
                "kind": row.kind,
                "purpose": row.purpose,
                "byte_size": row.byte_size,
                "status": row.status,
            },
        )

    async def authority(
        self, row: MCPNativeTransferModel, name: str, *, source_lifetime: bool = False
    ) -> MCPPrincipal:
        grant = await self.auth.require_grant(row.original_grant_id, lock=True)
        expiry = utc(row.expires_at)
        if source_lifetime:
            if (
                name != "inspect_native_transfer"
                or row.status != "completed"
                or row.kind not in {"upload_pdf", "upload_workbook"}
            ):
                raise MCPAuthError("access_denied", 403)
            source = await self.session.get(
                MCPArtifactModel if row.kind == "upload_pdf" else MCPContactImportUploadModel,
                row.artifact_id if row.kind == "upload_pdf" else row.workbook_id,
                populate_existing=True,
            )
            if source is None:
                raise ArtifactError("Transfer source is unavailable", 404)
            expiry = utc(source.expires_at)
        if (
            grant.user_id != row.user_id
            or grant.security_version != row.security_version
            or expiry <= datetime.now(UTC)
        ):
            raise MCPAuthError("access_denied", 403)
        capability = "mcp:export" if row.kind == "download" else "mcp:upload"
        self.auth.require_capability(grant, capability)
        await require_tool_access(
            self.session,
            self.settings,
            grant.id,
            name,
            capability,
            required_sections=frozenset({_SECTIONS[row.purpose]}),
            lock=False,
        )
        principal = MCPPrincipal(
            grant.id,
            grant.user_id,
            grant.client_id,
            tuple(grant.capabilities),
            min(expiry, utc(grant.expires_at)),
            grant.resource,
        )
        await self.target(principal, row)
        return principal

    async def target(self, principal: MCPPrincipal, row: MCPNativeTransferModel) -> None:
        await self.contact_service("contact_broadcast").agency(row.agency_id)
        if row.group_id is not None:
            await self.artifacts._group(
                principal,
                row.agency_id,
                row.group_id,
                "export" if row.kind == "download" else "upload",
            )
        if row.kind == "download":
            if row.artifact_id is None:
                raise ArtifactError("Transfer is unavailable", 404)
            artifact = await self.session.get(
                MCPArtifactModel, row.artifact_id, populate_existing=True
            )
            if (
                artifact is None
                or artifact.direction != "export"
                or artifact.purpose not in _EXPORT_TOOLS
            ):
                raise ArtifactError("Transfer is unavailable", 404)
            await require_tool_access(
                self.session,
                self.settings,
                principal.grant_id,
                _EXPORT_TOOLS[artifact.purpose],
                "mcp:export",
                lock=False,
            )
            source = await self.artifacts.get(principal, self.artifact_handle(row))
            if (
                source.agency_id,
                source.group_id,
                source.filename,
                source.byte_size,
                source.sha256,
                source.media_type,
            ) != (
                row.agency_id,
                row.group_id,
                row.filename,
                row.byte_size,
                row.sha256,
                row.media_type,
            ):
                raise ArtifactError("Transfer is unavailable", 404)

    def artifact_handle(self, row: MCPNativeTransferModel) -> str:
        if row.artifact_id is None:
            raise ArtifactError("Transfer is unavailable", 404)
        return self.artifacts._handle(row.artifact_id, row.user_id, row.original_grant_id)

    async def limited(
        self, identifier: uuid.UUID, secret: str, *, name: str, lock: bool = False
    ) -> tuple[MCPNativeTransferModel, MCPPrincipal]:
        if not TOKEN.fullmatch(secret):
            raise MCPAuthError("invalid_token", 401)
        statement = (
            select(MCPNativeTransferModel)
            .where(MCPNativeTransferModel.id == identifier)
            .execution_options(populate_existing=True)
        )
        row = await self.session.scalar(statement)
        if row is None or not hmac.compare_digest(
            credential_hash(secret, self.settings.app_secret_key), row.token_hash
        ):
            raise MCPAuthError("invalid_token", 401)
        principal = await self.authority(row, name)
        if lock:
            row = await self.session.scalar(statement.with_for_update())
            if row is None or not hmac.compare_digest(
                credential_hash(secret, self.settings.app_secret_key), row.token_hash
            ):
                raise MCPAuthError("invalid_token", 401)
            principal = await self.authority(row, name)
        return row, principal

    async def metadata(self, row: MCPNativeTransferModel) -> dict[str, Any]:
        target = (
            await self.session.get(ClientGroupModel, row.group_id)
            if row.group_id
            else await self.session.get(AgencyModel, row.agency_id)
        )
        return {
            "id": str(row.id),
            "kind": row.kind,
            "purpose": row.purpose,
            "status": row.status,
            "agency_id": str(row.agency_id),
            "group_id": str(row.group_id) if row.group_id else None,
            "document_type": row.document_type,
            "destination_label": target.name if target else "Prepared destination",
            "filename": row.filename,
            "media_type": row.media_type,
            "byte_size": row.byte_size,
            "sha256": row.sha256,
            "expires_at": utc(row.expires_at).isoformat(),
            "download_completed": row.download_completed_at is not None,
            "delivered": row.delivered_at is not None,
        }

    async def handoff(self, row: MCPNativeTransferModel) -> dict[str, Any]:
        secret = self.token(row)
        return {
            **await self.metadata(row),
            "content_url": f"{self.settings.mcp.public_origin}/mcp/native-transfers/{row.id}/content",
            "browser_url": f"{self.settings.mcp.frontend_origin}/mcp/file-transfer/{row.id}#token={secret}",
            "authorization_header": f"Bearer {secret}",
            "credential_usage": "Use only this ticket's exact content URL. Do not log or store its credential; the browser URL keeps it in the fragment.",
        }

    async def _creation(
        self,
        access_token: str,
        name: str,
        capability: str,
        purpose: str,
        kind: str,
        key: str,
        payload: dict[str, Any],
    ) -> tuple[MCPPrincipal, str, str, MCPNativeTransferModel | None]:
        if not isinstance(key, str) or not 16 <= len(key) <= 256 or any(ord(c) < 32 for c in key):
            raise ArtifactError("Provide a stable retry key of 16 to 256 characters", 422)
        # Serialize ticket quotas and uniqueness without control lock upgrades.
        control = await self.session.scalar(
            select(MCPControlModel).where(MCPControlModel.id == 1).with_for_update()
        )
        if control is None:
            raise MCPAuthError("temporarily_unavailable", 503)
        principal = await MCPOperationService(self.session, self.settings)._authorize(
            access_token,
            capability,
            tool_name=name,
            required_sections=frozenset({_SECTIONS[purpose]}),
        )
        key_hash = hashlib.sha256(("native-transfer-v1\0" + key).encode()).hexdigest()
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        existing = await self.session.scalar(
            select(MCPNativeTransferModel)
            .where(
                MCPNativeTransferModel.original_grant_id == principal.grant_id,
                MCPNativeTransferModel.kind == kind,
                MCPNativeTransferModel.idempotency_hash == key_hash,
            )
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise ArtifactError("This retry key belongs to different transfer input", 409)
            await self.authority(existing, name)
            return principal, key_hash, payload_hash, existing
        since = datetime.now(UTC) - timedelta(hours=1)
        recent = await self.session.scalar(
            select(func.count())
            .select_from(MCPNativeTransferModel)
            .where(MCPNativeTransferModel.created_at >= since)
        )
        own = await self.session.scalar(
            select(func.count())
            .select_from(MCPNativeTransferModel)
            .where(
                MCPNativeTransferModel.original_grant_id == principal.grant_id,
                MCPNativeTransferModel.created_at >= since,
            )
        )
        if (recent or 0) >= 1000 or (own or 0) >= 30:
            raise ArtifactError("Native transfer request capacity is busy; retry later", 429)
        return principal, key_hash, payload_hash, None

    async def create_upload(
        self, access_token: str, request: MCPNativeUploadRequest, idempotency_key: str
    ) -> dict[str, Any]:
        kind = "upload_pdf" if request.purpose == "document_pdf" else "upload_workbook"
        maximum = self.settings.upload_max_file_size_bytes if kind == "upload_pdf" else MAX_BYTES
        if request.byte_size > maximum:
            raise ArtifactError("File exceeds the current upload lane limit", 413)
        principal, key_hash, payload_hash, existing = await self._creation(
            access_token,
            "create_native_upload",
            "mcp:upload",
            request.purpose,
            kind,
            idempotency_key,
            request.model_dump(mode="json"),
        )
        if existing is not None:
            return await self.handoff(existing)
        grant = await self.auth.require_grant(principal.grant_id, lock=True)
        now = datetime.now(UTC)
        row = MCPNativeTransferModel(
            id=uuid.uuid4(),
            original_grant_id=grant.id,
            user_id=grant.user_id,
            security_version=grant.security_version,
            kind=kind,
            purpose=request.purpose,
            agency_id=request.agency_id,
            group_id=request.group_id,
            document_type=request.document_type,
            filename=_filename(request.filename, ".pdf" if kind == "upload_pdf" else ".xlsx"),
            media_type="application/pdf" if kind == "upload_pdf" else XLSX_MEDIA,
            byte_size=request.byte_size,
            sha256=request.sha256,
            idempotency_hash=key_hash,
            payload_hash=payload_hash,
            token_hash="",
            status="pending",
            created_at=now,
            expires_at=min(now + TTL, utc(principal.expires_at)),
        )
        row.token_hash = credential_hash(self.token(row), self.settings.app_secret_key)
        await self.target(principal, row)
        self.session.add(row)
        await self.session.flush()
        await self.audit(row, "created")
        return await self.handoff(row)

    async def create_download(
        self, access_token: str, artifact_handle: str, idempotency_key: str
    ) -> dict[str, Any]:
        principal, key_hash, payload_hash, existing = await self._creation(
            access_token,
            "create_native_download",
            "mcp:export",
            "export",
            "download",
            idempotency_key,
            {"artifact_handle": artifact_handle},
        )
        if existing is not None:
            return await self.handoff(existing)
        artifact = await self.artifacts.get(principal, artifact_handle, lock=True)
        if artifact.direction != "export" or artifact.byte_size > MAX_NATIVE_DOWNLOAD_BYTES:
            raise ArtifactError(
                "Native downloads support generated exports up to 128 MiB; split a larger selection",
                413,
            )
        access_handle = self.artifacts._handle(artifact.id, principal.user_id, principal.grant_id)
        if not hmac.compare_digest(access_handle, artifact_handle):
            raise ArtifactError("Resume this export to obtain its current native locator", 409)
        grant = await self.auth.require_grant(principal.grant_id, lock=True)
        now = datetime.now(UTC)
        row = MCPNativeTransferModel(
            id=uuid.uuid4(),
            original_grant_id=grant.id,
            user_id=grant.user_id,
            security_version=grant.security_version,
            kind="download",
            purpose="export",
            agency_id=artifact.agency_id,
            group_id=artifact.group_id,
            filename=artifact.filename,
            media_type=artifact.media_type,
            byte_size=artifact.byte_size,
            sha256=artifact.sha256,
            idempotency_hash=key_hash,
            payload_hash=payload_hash,
            token_hash="",
            status="pending",
            created_at=now,
            expires_at=min(now + TTL, utc(principal.expires_at), utc(artifact.expires_at)),
            artifact_id=artifact.id,
        )
        row.token_hash = credential_hash(self.token(row), self.settings.app_secret_key)
        await self.target(principal, row)
        self.session.add(row)
        await self.session.flush()
        await self.audit(row, "created")
        return await self.handoff(row)

    async def inspect(self, access_token: str, identifier: uuid.UUID) -> dict[str, Any]:
        principal = await MCPOperationService(self.session, self.settings)._authorize(access_token)
        row = await self.session.scalar(
            select(MCPNativeTransferModel).where(
                MCPNativeTransferModel.id == identifier,
                MCPNativeTransferModel.original_grant_id == principal.grant_id,
                MCPNativeTransferModel.user_id == principal.user_id,
            )
        )
        if row is None:
            raise ArtifactError("Transfer is unavailable", 404)
        await self.authority(
            row,
            "inspect_native_transfer",
            source_lifetime=row.status == "completed" and row.kind != "download",
        )
        result = await self.metadata(row)
        if row.status == "completed" and row.kind == "upload_pdf":
            result["staged_source"] = await self.artifacts.describe(
                await self.artifacts.get(principal, self.artifact_handle(row)),
                self.artifact_handle(row),
            )
        elif row.status == "completed" and row.kind == "upload_workbook" and row.workbook_id:
            source = await self.session.get(MCPContactImportUploadModel, row.workbook_id)
            if source is None:
                raise ArtifactError("Transfer is unavailable", 404)
            binding = f"gc-mcp-contacts-v1\0{source.id}\0{principal.user_id}\0{principal.grant_id}".encode()
            handle = "gcmcp_contacts_" + base64.urlsafe_b64encode(
                hmac.digest(self.settings.app_secret_key.encode(), binding, "sha384")
            ).decode().rstrip("=")
            service = self.contact_service(row.purpose)
            source = await service.get(principal, handle)
            result["staged_source"] = service.metadata(source, handle)
        return result
