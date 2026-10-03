"""Bounded private transfer primitives; no generic paths or business import side effects.

Callers own the database transaction. Temporary objects are immutable transfer
copies, never source documents. A storage lifecycle must expire orphaned copies.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import tempfile
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, cast

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, credential_hash, utc
from app.application.mcp.permissions import require_tool_access
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.complete_export_delivery import (
    complete_export_delivery,
    validate_export_checkpoint,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError, StorageError
from app.infrastructure.database.mcp_artifact_models import MCPArtifactAccessModel, MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    DocumentDistributionBatchModel,
    PassportExportHistoryModel,
)
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService
from app.infrastructure.storage.mcp_artifact_storage import MCPArtifactStorage

CHUNK_BYTES = 64 * 1024
MAX_EXPORT_BYTES = 512 * 1024 * 1024
_HANDLE = re.compile(r"gcmcp_artifact_[A-Za-z0-9_-]{64}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_PURPOSES = {
    "travel_tracker_excel": (
        "export",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "group_document_pdf": ("upload", "application/pdf", ".pdf"),
    "passport_excel": (
        "export",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "passport_images": ("export", "application/zip", ".zip"),
    "whatsapp_tracking_excel": (
        "export",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "rooming_list_excel": (
        "export",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "document_assignments_excel": (
        "export",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "rooming_checkins_excel": (
        "export",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
}
# Shared by all service instances in one process; reject saturation immediately.
# Across deployment workers the upper bound is 2 * worker_count active transfers.
_TRANSFERS = anyio.CapacityLimiter(2)


class ArtifactError(ValueError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


@asynccontextmanager
async def transfer_slot() -> AsyncIterator[None]:
    borrower = object()
    try:
        _TRANSFERS.acquire_on_behalf_of_nowait(borrower)
    except anyio.WouldBlock as exc:
        raise ArtifactError("Transfer capacity is busy; retry later", 503) from exc
    try:
        yield
    finally:
        _TRANSFERS.release_on_behalf_of(borrower)


async def _spool(body: AsyncIterable[bytes], target: BinaryIO, *, maximum: int) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    async with asyncio.timeout(120):
        async for part in body:
            if not isinstance(part, bytes):
                raise ArtifactError("Invalid transfer data", 400)
            total += len(part)
            if total > maximum:
                raise ArtifactError("Transfer exceeds the permitted size", 413)
            digest.update(part)
            # Disk writes run off the event loop and finish before cleanup.
            for offset in range(0, len(part), CHUNK_BYTES):
                bounded = part[offset : offset + CHUNK_BYTES]
                await run_bounded_storage_operations(
                    [lambda: asyncio.to_thread(target.write, bounded)], concurrency=1
                )
    if total == 0:
        raise ArtifactError("Transfer is empty", 422)
    target.seek(0)
    return total, digest.hexdigest()


def _filename(value: str, extension: str) -> str:
    basename = value.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = re.sub(r"[^A-Za-z0-9._-]", "-", basename).strip(".-_")[:95]
    return (stem or "document") + extension


def _checkpoint_hash(history: PassportExportHistoryModel) -> str:
    frozen = {
        "history_id": str(history.id),
        "group_id": str(history.group_id),
        "agency_id": str(history.agency_id),
        "user_id": str(history.created_by_user_id),
        "kind": history.export_kind,
        "mode": history.export_mode,
        "baseline_id": str(history.baseline_export_id),
        "version": history.format_version,
        "snapshot_ids": history.snapshot_submission_ids,
        "exported_ids": history.exported_submission_ids,
        "people": history.exported_people_snapshot,
        "total": history.total_available_count,
        "exported": history.exported_count,
        "pending": history.pending_recipient_count,
        "artifact_metadata": history.artifact_metadata,
    }
    return hashlib.sha256(
        json.dumps(frozen, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class MCPArtifactService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        storage: MCPArtifactStorage | None = None,
        security: UploadSecurityService | None = None,
    ):
        self.session, self.settings = session, settings
        self._storage = storage
        self.security = security
        self.auth = MCPAuthorizationService(session, settings)

    @property
    def storage(self) -> MCPArtifactStorage:
        # DB-only inspection/receipt callbacks never initialize a provider client.
        if self._storage is None:
            self._storage = MCPArtifactStorage()
        return self._storage

    def _handle(self, artifact_id: uuid.UUID, user_id: uuid.UUID, grant_id: uuid.UUID) -> str:
        message = f"gc-mcp-artifact-handle-v1\0{artifact_id}\0{user_id}\0{grant_id}".encode()
        signature = hmac.digest(self.settings.app_secret_key.encode(), message, "sha384")
        return "gcmcp_artifact_" + base64.urlsafe_b64encode(signature).decode().rstrip("=")

    async def _associations(self, principal: MCPPrincipal, row: MCPArtifactModel) -> None:
        pairs = row.association_groups
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 100:
            raise ArtifactError("Artifact associations are unavailable", 404)
        seen = set()
        for pair in pairs:
            try:
                if set(pair) != {"agency_id", "group_id"}:
                    raise ValueError()
                agency_id, group_id = uuid.UUID(pair["agency_id"]), uuid.UUID(pair["group_id"])
            except (TypeError, ValueError, KeyError) as exc:
                raise ArtifactError("Artifact associations are unavailable", 404) from exc
            if (agency_id, group_id) in seen:
                raise ArtifactError("Artifact associations are unavailable", 404)
            seen.add((agency_id, group_id))
            await self._group(principal, agency_id, group_id, row.direction)
        if (row.agency_id, row.group_id) not in seen:
            raise ArtifactError("Artifact associations are unavailable", 404)

    async def _authority(
        self,
        principal: MCPPrincipal,
        capability: str,
        *,
        lock: bool = False,
        tool_name: str | None = None,
    ) -> None:
        if utc(principal.expires_at) <= datetime.now(UTC):
            raise MCPAuthError("invalid_token", 401)
        grant = await self.auth.require_grant(principal.grant_id, lock=lock)
        if (
            grant.user_id != principal.user_id
            or grant.resource != principal.resource
            or grant.client_id != principal.client_id
        ):
            raise MCPAuthError("invalid_token", 401)
        self.auth.require_capability(grant, capability)
        await require_tool_access(
            self.session,
            self.settings,
            grant.id,
            tool_name
            or ("upload_document_pdf" if capability == "mcp:upload" else "download_export"),
            capability,
            lock=lock,
        )

    async def _group(
        self, principal: MCPPrincipal, agency_id: uuid.UUID, group_id: uuid.UUID, direction: str
    ) -> User:
        group = await self.session.scalar(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == group_id,
                ClientGroupModel.agency_id == agency_id,
                ClientGroupModel.deleted_at.is_(None),
                ClientGroupModel.status != "deleted",
            )
            .execution_options(populate_existing=True)
        )
        if group is None:
            raise ArtifactError("Group was not found", 404)
        user = await UserRepository(self.session).get_by_id(principal.user_id)
        if user is None:
            raise MCPAuthError("invalid_token", 401)
        policy = AuthorizationPolicy(self.session)
        try:
            if direction == "upload":
                await policy.require_manage_group(user, group)
            else:
                await policy.require_export_data(user, group)
        except AuthorizationError as exc:
            raise ArtifactError("Group was not found", 404) from exc
        return user

    async def _history(self, artifact: MCPArtifactModel) -> PassportExportHistoryModel:
        if artifact.export_history_id is None:
            raise ArtifactError("Prepared export was not found", 404)
        history = await PassportExportHistoryRepository(self.session).get_for_completion(
            history_id=artifact.export_history_id,
            group_id=artifact.group_id,
            agency_id=artifact.agency_id,
            created_by_user_id=artifact.user_id,
        )
        if history is None or history.export_kind != artifact.purpose:
            raise ArtifactError("Prepared export was not found", 404)
        validate_export_checkpoint(history)
        if artifact.export_checkpoint_sha256 is not None and not hmac.compare_digest(
            artifact.export_checkpoint_sha256, _checkpoint_hash(history)
        ):
            raise ArtifactError("Prepared export checkpoint changed")
        return history

    async def stage_pdf(
        self,
        principal: MCPPrincipal,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        filename: str,
        body: AsyncIterable[bytes],
        expected_size: int,
        expected_sha256: str,
    ) -> dict[str, object]:
        await self._authority(principal, "mcp:upload")
        await self._group(principal, agency_id, group_id, "upload")
        maximum = self.settings.upload_max_file_size_bytes
        if not 1 <= expected_size <= maximum or not _DIGEST.fullmatch(expected_sha256):
            raise ArtifactError("Invalid upload size or checksum", 422)
        async with transfer_slot(), asyncio.timeout(120):
            with tempfile.TemporaryFile(mode="w+b") as temporary:
                staged = cast(BinaryIO, temporary)
                size, checksum = await _spool(body, staged, maximum=maximum)
                if size != expected_size or not hmac.compare_digest(checksum, expected_sha256):
                    raise ArtifactError("Upload size or checksum does not match", 422)
                # Existing scanner/parser needs bytes. This one buffer is capped
                # by the existing per-file limit, after streaming ingress to disk.
                content = (
                    await run_bounded_storage_operations(
                        [lambda: asyncio.to_thread(staged.read, maximum + 1)], concurrency=1
                    )
                )[0]
                security = self.security or UploadSecurityService(settings=self.settings)
                await security.validate_document(
                    content=content,
                    declared_content_type="application/pdf",
                    context=UploadSecurityContext(
                        ingestion_flow="mcp_group_document_pdf",
                        agency_id=agency_id,
                        user_id=principal.user_id,
                    ),
                    max_bytes=maximum,
                )
                del content
                return await self._store(
                    principal,
                    agency_id=agency_id,
                    group_id=group_id,
                    purpose="group_document_pdf",
                    filename=filename,
                    staged=staged,
                    size=size,
                    checksum=checksum,
                )

    async def prepare_export(
        self,
        principal: MCPPrincipal,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        purpose: str,
        filename: str,
        body: AsyncIterable[bytes],
        export_history_id: uuid.UUID | None = None,
        association_groups: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        """Code-only adapter entry point; HTTP clients cannot register arbitrary bytes/keys."""
        if purpose not in _PURPOSES or _PURPOSES[purpose][0] != "export":
            raise ArtifactError("Unsupported export purpose", 422)
        await self._authority(principal, "mcp:export")
        await self._group(principal, agency_id, group_id, "export")
        async with transfer_slot(), asyncio.timeout(120):
            with tempfile.TemporaryFile(mode="w+b") as temporary:
                staged = cast(BinaryIO, temporary)
                size, checksum = await _spool(body, staged, maximum=MAX_EXPORT_BYTES)
                return await self._store(
                    principal,
                    agency_id=agency_id,
                    group_id=group_id,
                    purpose=purpose,
                    filename=filename,
                    staged=staged,
                    size=size,
                    checksum=checksum,
                    export_history_id=export_history_id,
                    association_groups=association_groups,
                )

    async def _store(
        self,
        principal: MCPPrincipal,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        purpose: str,
        filename: str,
        staged: BinaryIO,
        size: int,
        checksum: str,
        export_history_id: uuid.UUID | None = None,
        association_groups: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        direction, media_type, extension = _PURPOSES[purpose]
        await self._authority(
            principal, f"mcp:{'upload' if direction == 'upload' else 'export'}", lock=True
        )
        await self._group(principal, agency_id, group_id, direction)
        identifier = uuid.uuid4()
        handle = self._handle(identifier, principal.user_id, principal.grant_id)
        now = datetime.now(UTC)
        row = MCPArtifactModel(
            id=identifier,
            handle_hash=credential_hash(handle, self.settings.app_secret_key),
            user_id=principal.user_id,
            grant_id=principal.grant_id,
            agency_id=agency_id,
            group_id=group_id,
            association_groups=(
                association_groups
                if association_groups is not None
                else [{"agency_id": str(agency_id), "group_id": str(group_id)}]
            ),
            direction=direction,
            purpose=purpose,
            storage_key=f"mcp-transfers/v1/{identifier}",
            filename=_filename(filename, extension),
            media_type=media_type,
            byte_size=size,
            sha256=checksum,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            export_history_id=export_history_id,
        )
        await self._associations(principal, row)
        if export_history_id is not None:
            history = await self._history(row)
            row.export_checkpoint_sha256 = _checkpoint_hash(history)
            if history.status != "prepared" or history.completed_at is not None:
                raise ArtifactError("Export is already completed")
            if await self.session.scalar(
                select(MCPArtifactModel.id).where(
                    MCPArtifactModel.export_history_id == export_history_id
                )
            ):
                raise ArtifactError("Export already has a temporary artifact")
        await self.storage.put_transfer(
            staged, key=row.storage_key, size=size, sha256=checksum, media_type=media_type
        )
        self.session.add(row)
        await self.session.flush()
        self.session.add(
            MCPArtifactAccessModel(
                artifact_id=row.id,
                grant_id=principal.grant_id,
                handle_hash=row.handle_hash,
                handle_version=1,
                created_at=now,
            )
        )
        await self.session.flush()
        await self.audit("prepared" if direction == "export" else "staged", row)
        return self.metadata(row, handle)

    async def get(
        self, principal: MCPPrincipal, handle: str, *, lock: bool = False
    ) -> MCPArtifactModel:
        if not _HANDLE.fullmatch(handle):
            raise ArtifactError("Artifact was not found", 404)
        # Foreign handles return the same answer regardless of capability.
        stmt = (
            select(MCPArtifactModel)
            .join(MCPArtifactAccessModel, MCPArtifactAccessModel.artifact_id == MCPArtifactModel.id)
            .where(
                MCPArtifactAccessModel.handle_hash
                == credential_hash(handle, self.settings.app_secret_key),
                MCPArtifactModel.user_id == principal.user_id,
                MCPArtifactAccessModel.grant_id == principal.grant_id,
            )
            .execution_options(populate_existing=True)
        )
        row = await self.session.scalar(stmt)
        if row is None or utc(row.expires_at) <= datetime.now(UTC):
            raise ArtifactError("Artifact was not found", 404)
        await self._authority(principal, f"mcp:{row.direction}", lock=lock)
        if row.purpose == "travel_tracker_excel":
            await require_tool_access(
                self.session, self.settings, principal.grant_id,
                "prepare_travel_tracker_export", "mcp:export", lock=lock,
            )
        if lock:
            row = await self.session.scalar(stmt.with_for_update())
            if row is None or utc(row.expires_at) <= datetime.now(UTC):
                raise ArtifactError("Artifact was not found", 404)
        await self._associations(principal, row)
        return row

    async def recover_export(
        self, principal: MCPPrincipal, artifact_id: uuid.UUID
    ) -> dict[str, object]:
        """Code-only receipt recovery; never exposed as an arbitrary artifact-id endpoint."""
        await self._authority(principal, "mcp:export", lock=True)
        row = await self.session.scalar(
            select(MCPArtifactModel)
            .where(
                MCPArtifactModel.id == artifact_id,
                MCPArtifactModel.user_id == principal.user_id,
                MCPArtifactModel.direction == "export",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or utc(row.expires_at) <= datetime.now(UTC):
            raise ArtifactError("Export artifact is unavailable or expired", 404)
        await self._associations(principal, row)
        if row.export_history_id is not None:
            await self._history(row)
        access = await self.session.get(MCPArtifactAccessModel, (row.id, principal.grant_id))
        if access is not None and access.handle_version == 0:
            raise ArtifactError("Legacy artifact receipt cannot be reconstructed")
        handle = self._handle(row.id, principal.user_id, principal.grant_id)
        digest = credential_hash(handle, self.settings.app_secret_key)
        if access is None:
            self.session.add(
                MCPArtifactAccessModel(
                    artifact_id=row.id,
                    grant_id=principal.grant_id,
                    handle_hash=digest,
                    handle_version=1,
                )
            )
            await AuditLogRepository(self.session).record(
                action="mcp.artifact_access_recovered",
                entity_type="mcp_artifact",
                entity_id=str(row.id),
                agency_id=row.agency_id,
                user_id=principal.user_id,
                metadata={"grant_id": str(principal.grant_id), "purpose": row.purpose},
            )
            await self.session.flush()
        elif not hmac.compare_digest(access.handle_hash, digest):
            raise ArtifactError("Artifact receipt cannot be reconstructed")
        return self.metadata(row, handle)

    async def ingestion_source(
        self,
        principal: MCPPrincipal,
        *,
        artifact_id: uuid.UUID,
        operation_id: uuid.UUID,
        explicit_resume: bool,
    ) -> MCPArtifactModel:
        """Code-only source access for a previously claimed ingestion receipt."""
        await self._authority(principal, "mcp:upload", lock=True)
        row = await self.session.scalar(
            select(MCPArtifactModel)
            .where(
                MCPArtifactModel.id == artifact_id,
                MCPArtifactModel.user_id == principal.user_id,
                MCPArtifactModel.direction == "upload",
                MCPArtifactModel.purpose == "group_document_pdf",
                MCPArtifactModel.ingestion_operation_id == operation_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or utc(row.expires_at) <= datetime.now(UTC):
            raise ArtifactError("Ingestion source is unavailable or expired", 404)
        await self._associations(principal, row)
        access = await self.session.get(MCPArtifactAccessModel, (row.id, principal.grant_id))
        if not explicit_resume and principal.grant_id != row.grant_id:
            raise ArtifactError("Resume this ingestion explicitly from the new connection", 403)
        if access is None:
            if not explicit_resume:
                raise ArtifactError("Ingestion source was not found", 404)
            self.session.add(
                MCPArtifactAccessModel(
                    artifact_id=row.id,
                    grant_id=principal.grant_id,
                    handle_version=1,
                    handle_hash=credential_hash(
                        self._handle(row.id, principal.user_id, principal.grant_id),
                        self.settings.app_secret_key,
                    ),
                )
            )
            await self.audit("ingestion_access_recovered", row, grant_id=principal.grant_id)
            await self.session.flush()
        return row

    async def describe(self, row: MCPArtifactModel, handle: str) -> dict[str, object]:
        result = self.metadata(row, handle)
        if row.direction != "upload" or row.ingestion_operation_id is None:
            return result
        operation = await self.session.get(MCPOperationModel, row.ingestion_operation_id)
        result["business_ingestion"] = "unavailable"
        if (
            operation is not None
            and operation.user_id == row.user_id
            and operation.operation_name == "ingest_document_pdf"
        ):
            if operation.status in {"queued", "running", "failed", "unknown"}:
                result["business_ingestion"] = operation.status
            elif operation.status == "succeeded":
                batch = await self.session.scalar(
                    select(DocumentDistributionBatchModel).where(
                        DocumentDistributionBatchModel.id == operation.id,
                        DocumentDistributionBatchModel.agency_id == row.agency_id,
                        DocumentDistributionBatchModel.group_id == row.group_id,
                    )
                )
                if batch is not None:
                    result["business_ingestion"] = "ingested"
        return result

    @staticmethod
    def metadata(row: MCPArtifactModel, handle: str) -> dict[str, object]:
        return {
            "artifact_id": handle,
            "direction": row.direction,
            "purpose": row.purpose,
            "agency_id": str(row.agency_id),
            "group_id": str(row.group_id),
            "association_groups": row.association_groups,
            "filename": row.filename,
            "media_type": row.media_type,
            "byte_size": row.byte_size,
            "sha256": row.sha256,
            "expires_at": utc(row.expires_at).isoformat(),
            "content_path": f"/mcp/artifacts/{handle}/content",
            "delivery_ack_required": row.direction == "export",
            "delivered_at": utc(row.delivered_at).isoformat() if row.delivered_at else None,
            "business_ingestion": ("claimed" if row.ingestion_operation_id else "not_started")
            if row.direction == "upload"
            else None,
            "ingestion_operation_id": str(row.ingestion_operation_id)
            if row.ingestion_operation_id
            else None,
        }

    async def validate_storage(self, row: MCPArtifactModel) -> None:
        stat = await self.storage.stat_file(row.storage_key)
        if stat.size_bytes != row.byte_size or stat.checksum_sha256 != row.sha256:
            raise StorageError("Artifact integrity metadata changed")

    async def stream(
        self, principal: MCPPrincipal, handle: str, row: MCPArtifactModel
    ) -> AsyncIterator[bytes]:
        # The HTTP boundary acquires a slot before committing response headers.
        checksum, size = hashlib.sha256(), 0
        async with asyncio.timeout(120):
            async for part in self.storage.stream_file(
                row.storage_key, start=0, expected_bytes=row.byte_size, chunk_size=CHUNK_BYTES
            ):
                if datetime.now(UTC) >= min(utc(row.expires_at), utc(principal.expires_at)):
                    raise ArtifactError("Transfer authorization expired", 401)
                size += len(part)
                if size > row.byte_size:
                    raise StorageError("Artifact exceeded authorized size")
                checksum.update(part)
                yield part
        if size != row.byte_size or not hmac.compare_digest(checksum.hexdigest(), row.sha256):
            raise StorageError("Artifact checksum verification failed")
        current = await self.get(principal, handle, lock=True)
        current.download_completed_at = datetime.now(UTC)
        await self.audit("stream_completed", current, grant_id=principal.grant_id)
        await self.session.flush()

    async def acknowledge(
        self, principal: MCPPrincipal, handle: str, *, byte_size: int, sha256: str
    ) -> dict[str, object]:
        row = await self.get(principal, handle, lock=True)
        if row.direction != "export" or row.download_completed_at is None:
            raise ArtifactError("Export must be completely downloaded before acknowledgement")
        if (
            byte_size != row.byte_size
            or not _DIGEST.fullmatch(sha256)
            or not hmac.compare_digest(sha256, row.sha256)
        ):
            raise ArtifactError("Delivery size or checksum does not match", 422)
        if row.delivered_at is None:
            actor = await self._group(principal, row.agency_id, row.group_id, row.direction)
            if row.export_history_id is not None:
                await complete_export_delivery(
                    history=await self._history(row),
                    actor=actor,
                    agency_id=row.agency_id,
                    audit=AuditLogRepository(self.session),
                )
            row.delivered_at = datetime.now(UTC)
            await self.audit("delivery_acknowledged", row, grant_id=principal.grant_id)
            await self.session.flush()
        return self.metadata(row, handle)

    async def audit(
        self, action: str, row: MCPArtifactModel, *, grant_id: uuid.UUID | None = None
    ) -> None:
        await AuditLogRepository(self.session).record(
            action=f"mcp.artifact_{action}",
            entity_type="mcp_artifact",
            entity_id=str(row.id),
            agency_id=row.agency_id,
            user_id=row.user_id,
            metadata={
                "grant_id": str(grant_id or row.grant_id),
                "group_id": str(row.group_id),
                "purpose": row.purpose,
                "byte_size": row.byte_size,
            },
        )
