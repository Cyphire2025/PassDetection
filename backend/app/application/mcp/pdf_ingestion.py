"""Append-only staged PDF ingestion into the canonical retained-draft workflow.

The request receipt/one-artifact claim commits before any parsing or storage.
Execution is synchronous and explicitly resumable, not a broker/OCR job. The
canonical ingestion service compensates only newly created document copies.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import CHUNK_BYTES, ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import utc
from app.application.mcp.native_source_bindings import require_native_pdf_source
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
    MCPOperationProgress,
    MCPOperationService,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import PassportSubmission, User
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
    PassportSubmissionModel,
)
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionResult,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import DocumentMatcher, PassengerIdentifier
from app.infrastructure.documents.pdf_parser_sandbox import bounded_pdf_batch_timeout_seconds
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
    run_bounded_storage_operations,
)
from app.infrastructure.documents.verification_staging import verification_scope_fingerprints
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService
from app.infrastructure.storage.minio_repository import MinioStorageRepository

INGEST_PDF_POLICY = MCPToolPolicy(
    "ingest_document_pdf", MCPCapability.UPLOAD, frozenset({"append_document_draft"})
)
_INGESTIONS = anyio.CapacityLimiter(2)
DocumentLane = Literal[
    "visa",
    "flight_ticket",
    "flight_ticket_arrival",
    "flight_ticket_domestic",
    "flight_ticket_domestic_arrival",
    "other",
]


class PDFIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str = Field(pattern=r"^gcmcp_artifact_[A-Za-z0-9_-]{64}$")
    agency_id: uuid.UUID
    group_id: uuid.UUID
    document_type: DocumentLane


class PDFIngestCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload: PDFIngestRequest
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class PDFIngestReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_uuid: uuid.UUID
    agency_id: uuid.UUID
    group_id: uuid.UUID
    document_type: DocumentLane
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_size: int = Field(gt=0)


@dataclass(frozen=True)
class PDFIngestionSupport:
    passengers: Callable[..., Any]
    linked_source: Callable[..., Any]
    identifiers: Callable[..., Any]
    roster_snapshot: Callable[..., Any]
    enforce_capacity: Callable[..., Any]
    scope_lock: Callable[..., Any]
    blocking_upload: Callable[..., Any]
    receipt: Callable[..., DocumentUploadChunkModel]


@dataclass(frozen=True)
class _Snapshot:
    actor: User
    passengers: list[PassportSubmission]
    identifiers: tuple[PassengerIdentifier, ...]
    revision: str


class _AlreadyIngested(Exception):
    pass


class MCPPDFIngestionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        support: PDFIngestionSupport,
        *,
        artifacts: MCPArtifactService | None = None,
        document_storage: MinioStorageRepository | None = None,
    ):
        self.session, self.settings, self.support = session, settings, support
        self.artifacts = artifacts or MCPArtifactService(session, settings)
        self.document_storage = document_storage

    async def _snapshot(
        self,
        principal: MCPPrincipal,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        document_type: str,
        source_hash: str,
        source_size: int,
        lock: bool,
    ) -> _Snapshot:
        actor = await self.artifacts._group(principal, agency_id, group_id, "upload")
        agency = await self.session.scalar(
            select(AgencyModel.id).where(
                AgencyModel.id == agency_id, AgencyModel.is_active.is_(True)
            )
        )
        if agency is None:
            raise ArtifactError("Agency is unavailable", 404)
        stmt = (
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == group_id,
                ClientGroupModel.agency_id == agency_id,
                ClientGroupModel.deleted_at.is_(None),
                ClientGroupModel.status != "deleted",
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            stmt = stmt.with_for_update(nowait=True)
            if self.session.get_bind().dialect.name == "postgresql":
                # Canonical source locking has a bounded wait behind legacy writers.
                await self.session.execute(text("SET LOCAL lock_timeout = '250ms'"))
        group = await self.session.scalar(stmt)
        if group is None:
            raise ArtifactError("Group was not found", 404)
        linked = await self.support.linked_source(
            self.session,
            group=group,
            lock=lock,
            max_source_rows=5000,
        )
        roster = (
            select(PassportSubmissionModel)
            .where(
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
            )
            .order_by(PassportSubmissionModel.id)
            .limit(5001)
            .execution_options(populate_existing=True)
        )
        if lock:
            roster = roster.with_for_update(nowait=True)
        roster_rows = (await self.session.scalars(roster)).all()
        if len(roster_rows) > 5000:
            raise ArtifactError("Document matching is limited to 5000 passengers", 413)
        passengers = await self.support.passengers(
            group_id, current_user=actor, session=self.session
        )
        if not passengers:
            raise ArtifactError("This group has no passengers to match documents against", 422)
        identifiers = await self.support.identifiers(
            self.session,
            group=group,
            passengers=passengers,
            matcher=DocumentMatcher(),
            source=linked,
        )
        fingerprints = verification_scope_fingerprints(
            roster_snapshot=self.support.roster_snapshot(passengers),
            source_snapshot=linked.snapshot,
            identifiers=identifiers,
        )
        revision = hashlib.sha256(
            json.dumps(
                [
                    str(agency_id),
                    str(group_id),
                    document_type,
                    source_hash,
                    source_size,
                    *fingerprints,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return _Snapshot(actor, passengers, identifiers, revision)

    @staticmethod
    def _request_source(request: PDFIngestRequest, row: MCPArtifactModel) -> None:
        if (
            row.direction != "upload"
            or row.purpose != "group_document_pdf"
            or row.agency_id != request.agency_id
            or row.group_id != request.group_id
        ):
            raise ArtifactError("Staged PDF does not belong to the requested group", 404)

    async def inspect(self, principal: MCPPrincipal, request: PDFIngestRequest) -> dict[str, Any]:
        row = await self.artifacts.get(principal, request.artifact_id)
        self._request_source(request, row)
        await require_native_pdf_source(
            self.session,
            principal,
            row,
            agency_id=request.agency_id,
            group_id=request.group_id,
            document_type=request.document_type,
        )
        snapshot = await self._snapshot(
            principal,
            agency_id=row.agency_id,
            group_id=row.group_id,
            document_type=request.document_type,
            source_hash=row.sha256,
            source_size=row.byte_size,
            lock=False,
        )
        return {
            "upload": request.model_dump(mode="json"),
            "expected_revision": snapshot.revision,
            "passenger_count": len(snapshot.passengers),
            "filename": row.filename,
            "byte_size": row.byte_size,
            "sha256": row.sha256,
            "ingestion_operation_id": str(row.ingestion_operation_id)
            if row.ingestion_operation_id
            else None,
            "result_stage": "draft_for_review",
            "background_processing": False,
        }

    async def _operation(
        self, principal: MCPPrincipal, operation_id: uuid.UUID
    ) -> MCPOperationModel:
        row = await self.session.scalar(
            select(MCPOperationModel)
            .where(
                MCPOperationModel.id == operation_id,
                MCPOperationModel.user_id == principal.user_id,
                MCPOperationModel.operation_name == INGEST_PDF_POLICY.name,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.initial_result is None:
            raise MCPOperationError("operation_not_found")
        return row

    async def _completed(
        self,
        principal: MCPPrincipal,
        operation: MCPOperationModel,
        receipt: PDFIngestReceipt,
    ) -> dict[str, Any]:
        source = await self.session.scalar(
            select(MCPArtifactModel)
            .where(
                MCPArtifactModel.id == receipt.artifact_uuid,
                MCPArtifactModel.user_id == principal.user_id,
                MCPArtifactModel.ingestion_operation_id == operation.id,
            )
            .execution_options(populate_existing=True)
        )
        if source is None:
            raise ArtifactError(
                "The retained ingestion association is unavailable; it will not be recreated", 404
            )
        # The temporary bytes may expire; retained business rows do not. Every
        # retained association still needs current authority before result replay.
        await self.artifacts._associations(principal, source)
        await require_native_pdf_source(
            self.session,
            principal,
            source,
            agency_id=receipt.agency_id,
            group_id=receipt.group_id,
            document_type=receipt.document_type,
        )
        batch = await self.session.scalar(
            select(DocumentDistributionBatchModel)
            .where(
                DocumentDistributionBatchModel.id == operation.id,
                DocumentDistributionBatchModel.agency_id == receipt.agency_id,
                DocumentDistributionBatchModel.group_id == receipt.group_id,
                DocumentDistributionBatchModel.document_type == receipt.document_type,
                DocumentDistributionBatchModel.created_by_user_id == principal.user_id,
            )
            .execution_options(populate_existing=True)
        )
        if batch is None:
            raise ArtifactError(
                "The retained ingestion result is unavailable; it will not be recreated", 404
            )
        chunk = await self.session.scalar(
            select(DocumentUploadChunkModel).where(
                DocumentUploadChunkModel.upload_id == operation.id,
                DocumentUploadChunkModel.agency_id == receipt.agency_id,
                DocumentUploadChunkModel.group_id == receipt.group_id,
                DocumentUploadChunkModel.document_type == receipt.document_type,
                DocumentUploadChunkModel.workflow == "distribution",
            )
        )
        if chunk is None:
            raise ArtifactError("The retained ingestion receipt is unavailable", 409)
        return {
            "operation_id": str(operation.id),
            "status": "succeeded",
            "business_ingestion": "ingested",
            "batch_id": str(batch.id),
            "batch_status": batch.status,
            "agency_id": str(receipt.agency_id),
            "group_id": str(receipt.group_id),
            "document_type": receipt.document_type,
            "accepted_file_count": chunk.accepted_count,
            "rejected_file_count": chunk.rejected_count,
            "assignment_count": batch.uploaded_count,
            "rejected_documents": chunk.rejected_documents,
            "review_required": batch.status != "saved",
            "background_processing": False,
            "application_path": f"/passports/groups/{receipt.group_id}",
        }

    async def execute(
        self,
        *,
        access_token: str,
        operation_id: uuid.UUID,
        explicit_resume: bool = False,
    ) -> dict[str, Any]:
        borrower = object()
        try:
            _INGESTIONS.acquire_on_behalf_of_nowait(borrower)
        except anyio.WouldBlock as exc:
            raise ArtifactError("PDF ingestion capacity is busy; resume later", 503) from exc
        try:
            return await self._execute(access_token, operation_id, explicit_resume)
        finally:
            _INGESTIONS.release_on_behalf_of(borrower)

    async def _execute(
        self, access_token: str, operation_id: uuid.UUID, explicit_resume: bool
    ) -> dict[str, Any]:
        operations = MCPOperationService(self.session, self.settings)
        principal = await operations._authorize(
            access_token, "mcp:upload", tool_name="ingest_document_pdf"
        )
        operation = await self._operation(principal, operation_id)
        assert operation.initial_result is not None
        receipt = PDFIngestReceipt.model_validate(operation.initial_result["data"])
        if not explicit_resume and principal.grant_id != operation.initial_grant_id:
            raise ArtifactError("Resume this ingestion explicitly from the new connection", 403)
        if operation.status == "succeeded":
            return await self._completed(principal, operation, receipt)
        if operation.status != "queued":
            raise MCPOperationError("ingestion_not_resumable")
        source = await self.artifacts.ingestion_source(
            principal,
            artifact_id=receipt.artifact_uuid,
            operation_id=operation_id,
            explicit_resume=explicit_resume,
        )
        await require_native_pdf_source(
            self.session,
            principal,
            source,
            agency_id=receipt.agency_id,
            group_id=receipt.group_id,
            document_type=receipt.document_type,
            lock=True,
        )
        if source.sha256 != receipt.source_sha256 or source.byte_size != receipt.source_size:
            raise ArtifactError("Staged PDF integrity metadata changed")
        snapshot = await self._snapshot(
            principal,
            agency_id=receipt.agency_id,
            group_id=receipt.group_id,
            document_type=receipt.document_type,
            source_hash=source.sha256,
            source_size=source.byte_size,
            lock=False,
        )
        self._revision(snapshot, receipt)
        filename, storage_key, expiry = source.filename, source.storage_key, utc(source.expires_at)
        # Capture plain bounded inputs, then release SQL locks before untrusted parsing.
        await self.session.commit()
        maximum = self.settings.upload_max_file_size_bytes
        if receipt.source_size > maximum:
            raise ArtifactError("Staged PDF exceeds the current upload limit", 413)
        content = bytearray()
        digest = hashlib.sha256()
        async with asyncio.timeout(120):
            async for part in self.artifacts.storage.stream_file(
                storage_key,
                start=0,
                expected_bytes=receipt.source_size,
                chunk_size=CHUNK_BYTES,
            ):
                if datetime.now(UTC) >= min(expiry, utc(principal.expires_at)):
                    raise ArtifactError("Ingestion source authorization expired", 401)
                if len(content) + len(part) > receipt.source_size:
                    raise ArtifactError("Staged PDF exceeded its authorized size", 422)
                content.extend(part)
                digest.update(part)
        if len(content) != receipt.source_size or not hmac.compare_digest(
            digest.hexdigest(), receipt.source_sha256
        ):
            raise ArtifactError("Staged PDF checksum changed", 422)
        data = bytes(content)
        del content
        security = self.artifacts.security or UploadSecurityService(settings=self.settings)
        await security.validate_document(
            content=data,
            declared_content_type="application/pdf",
            context=UploadSecurityContext(
                ingestion_flow="mcp_document_pdf_ingestion",
                agency_id=receipt.agency_id,
                user_id=principal.user_id,
            ),
        )

        async def authorize_persistence() -> tuple[uuid.UUID, str]:
            current = await operations._authorize(
                access_token, "mcp:upload", tool_name="ingest_document_pdf"
            )
            current_operation = await self._operation(current, operation_id)
            if current_operation.status == "succeeded":
                raise _AlreadyIngested()
            if current_operation.status != "queued" or current_operation.initial_result is None:
                raise MCPOperationError("ingestion_not_resumable")
            if PDFIngestReceipt.model_validate(current_operation.initial_result["data"]) != receipt:
                raise MCPOperationError("operation_receipt_unavailable")
            current_source = await self.artifacts.ingestion_source(
                current,
                artifact_id=receipt.artifact_uuid,
                operation_id=operation_id,
                explicit_resume=explicit_resume,
            )
            await require_native_pdf_source(
                self.session,
                current,
                current_source,
                agency_id=receipt.agency_id,
                group_id=receipt.group_id,
                document_type=receipt.document_type,
                lock=True,
            )
            locked = await self._snapshot(
                current,
                agency_id=receipt.agency_id,
                group_id=receipt.group_id,
                document_type=receipt.document_type,
                source_hash=receipt.source_sha256,
                source_size=receipt.source_size,
                lock=True,
            )
            self._revision(locked, receipt)
            if self.session.get_bind().dialect.name == "postgresql":
                await self.support.scope_lock(
                    self.session,
                    agency_id=receipt.agency_id,
                    group_id=receipt.group_id,
                    document_type=receipt.document_type,
                )
            await self.session.execute(
                select(DocumentDistributionBatchModel.id)
                .where(
                    DocumentDistributionBatchModel.agency_id == receipt.agency_id,
                    DocumentDistributionBatchModel.group_id == receipt.group_id,
                    DocumentDistributionBatchModel.document_type == receipt.document_type,
                )
                .order_by(DocumentDistributionBatchModel.id)
                .with_for_update(nowait=True)
            )
            if (
                await self.support.blocking_upload(
                    self.session,
                    group_id=receipt.group_id,
                    agency_id=receipt.agency_id,
                    document_type=receipt.document_type,
                    exclude_upload_id=operation_id,
                    lock=True,
                )
                is not None
            ):
                raise ArtifactError("An incomplete document upload must be resolved first")
            return locked.actor.id, locked.actor.email

        async def capacity(incoming_rows: int) -> None:
            await self.support.enforce_capacity(
                self.session,
                group_id=receipt.group_id,
                agency_id=receipt.agency_id,
                document_type=receipt.document_type,
                incoming_rows=incoming_rows,
            )

        ingestion_service = TravelDocumentIngestionService(
            self.session,
            storage=self.document_storage,
            matcher=DocumentMatcher(),
        )
        ingestion: TravelDocumentIngestionResult | None = None

        async def ingest() -> None:
            nonlocal ingestion
            ingestion = await ingestion_service.ingest(
                agency_id=receipt.agency_id,
                group_id=receipt.group_id,
                document_type=receipt.document_type,
                passengers=snapshot.passengers,
                files=[TravelDocumentFile(filename, data)],
                batch_id=operation_id,
                created_by_user_id=snapshot.actor.id,
                actor_email=snapshot.actor.email,
                audit_source="mcp_staged_pdf",
                supplemental_identifiers=snapshot.identifiers,
                isolate_pdf_parsing=True,
                parser_batch_timeout_seconds=bounded_pdf_batch_timeout_seconds(1),
                reject_common_unsupported_format=True,
                require_passenger_match=True,
                before_persistence=authorize_persistence,
                before_persistence_capacity=capacity,
            )

        try:
            await run_bounded_storage_operations([ingest], concurrency=1)
            assert ingestion is not None
            self.session.add(self.support.receipt(operation_id, receipt, ingestion))
            locked_operation = await self._operation(principal, operation_id)
            await operations.record_progress(
                operation_id=operation_id,
                expected_revision=locked_operation.revision,
                update=MCPOperationProgress(
                    status="succeeded",
                    progress=1,
                    stage="draft_for_review",
                    created_entities=(
                        MCPCreatedEntity(
                            "document_distribution_batch",
                            str(operation_id),
                            f"/passports/groups/{receipt.group_id}",
                        ),
                    ),
                ),
            )
            await self.session.flush()
            return await self._completed(principal, locked_operation, receipt)
        except _AlreadyIngested:
            current = await operations._authorize(
                access_token, "mcp:upload", tool_name="ingest_document_pdf"
            )
            completed = await self._operation(current, operation_id)
            return await self._completed(current, completed, receipt)
        except BaseException:
            await self.session.rollback()
            if ingestion is not None:
                await finish_cleanup_despite_cancellation(
                    ingestion_service._cleanup_owned_storage(
                        list(ingestion.created_storage_keys),
                        agency_id=receipt.agency_id,
                        batch_id=operation_id,
                        durable=True,
                    )
                )
            raise

    @staticmethod
    def _revision(snapshot: _Snapshot, receipt: PDFIngestReceipt) -> None:
        if not hmac.compare_digest(snapshot.revision, receipt.expected_revision):
            raise MCPOperationError("ingestion_revision_changed")


def pdf_ingestion_operation(
    settings: Settings, support: PDFIngestionSupport
) -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = PDFIngestCommand.model_validate(payload)
        service = MCPPDFIngestionService(context.session, settings, support)
        row = await service.artifacts.get(context.principal, command.upload.artifact_id, lock=True)
        service._request_source(command.upload, row)
        await require_native_pdf_source(
            context.session,
            context.principal,
            row,
            agency_id=command.upload.agency_id,
            group_id=command.upload.group_id,
            document_type=command.upload.document_type,
            lock=True,
        )
        if row.ingestion_operation_id is not None:
            raise MCPOperationError("artifact_already_claimed")
        receipt = PDFIngestReceipt(
            artifact_uuid=row.id,
            agency_id=row.agency_id,
            group_id=row.group_id,
            document_type=command.upload.document_type,
            expected_revision=command.expected_revision,
            source_sha256=row.sha256,
            source_size=row.byte_size,
        )
        snapshot = await service._snapshot(
            context.principal,
            agency_id=row.agency_id,
            group_id=row.group_id,
            document_type=receipt.document_type,
            source_hash=row.sha256,
            source_size=row.byte_size,
            lock=True,
        )
        service._revision(snapshot, receipt)
        row.ingestion_operation_id = context.operation_id
        await context.session.flush()
        return MCPDatabaseResult(receipt.model_dump(mode="json"), status="queued")

    async def authorize(context: MCPDatabaseContext, initial: dict[str, Any]) -> None:
        receipt = PDFIngestReceipt.model_validate(initial["data"])
        await MCPArtifactService(context.session, settings)._group(
            context.principal,
            receipt.agency_id,
            receipt.group_id,
            "upload",
        )
        source = await context.session.get(
            MCPArtifactModel, receipt.artifact_uuid, populate_existing=True
        )
        if source is None:
            raise ArtifactError("Staged PDF association is unavailable", 404)
        await require_native_pdf_source(
            context.session,
            context.principal,
            source,
            agency_id=receipt.agency_id,
            group_id=receipt.group_id,
            document_type=receipt.document_type,
            lock=True,
        )

    return MCPDatabaseOperation(INGEST_PDF_POLICY, mutate, authorize)
