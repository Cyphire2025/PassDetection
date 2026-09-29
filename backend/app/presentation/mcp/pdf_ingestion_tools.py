"""Typed staged-PDF ingestion; no replacement, approval, save or send controls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError
from sqlalchemy.exc import DBAPIError

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.mcp.pdf_ingestion import (
    MCPPDFIngestionService,
    PDFIngestionSupport,
    PDFIngestReceipt,
    PDFIngestRequest,
    pdf_ingestion_operation,
)
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.models import DocumentUploadChunkModel
from app.infrastructure.documents.distribution_capacity import DocumentDistributionCapacityError
from app.infrastructure.documents.distribution_ingestion import TravelDocumentIngestionResult
from app.infrastructure.documents.document_matcher import (
    DocumentParserUnavailableError,
    UnsupportedDocumentBatchFormatError,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository, AuditResult
from app.infrastructure.security.upload_security import UploadSecurityService
from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata,
    acquire_document_upload_scope_advisory_lock,
    new_document_chunk_receipt,
)
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_document_match_identifiers,
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _enforce_group_document_assignment_capacity,
    _first_blocking_processing_upload_id,
)
from app.presentation.api.v1.routes.document_distribution_scope import _group_passengers
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot,
)
from app.presentation.mcp.invocation import invoke_operation, mark_invocation_audited


def ingestion_support() -> PDFIngestionSupport:
    def receipt(
        operation_id: uuid.UUID, source: PDFIngestReceipt, result: TravelDocumentIngestionResult
    ) -> DocumentUploadChunkModel:
        return new_document_chunk_receipt(
            metadata=DocumentChunkMetadata(
                upload_id=operation_id,
                chunk_id=uuid.uuid5(operation_id, "mcp-pdf-0"),
                chunk_index=0,
                expected_chunk_count=1,
                expected_file_count=1,
            ),
            agency_id=source.agency_id,
            workflow="distribution",
            group_id=source.group_id,
            document_type=source.document_type,
            fingerprint=source.source_sha256,
            file_count=1,
            byte_count=source.source_size,
            accepted_count=1 - len(result.rejected),
            rejected_count=len(result.rejected),
            rejected_documents=[
                {
                    "filename": item.filename,
                    "detected_type": item.detected_type,
                    "reason": item.reason,
                }
                for item in result.rejected
            ],
        )

    return PDFIngestionSupport(
        _group_passengers,
        _read_linked_document_match_source,
        _linked_document_match_identifiers,
        _document_match_roster_snapshot,
        _enforce_group_document_assignment_capacity,
        acquire_document_upload_scope_advisory_lock,
        _first_blocking_processing_upload_id,
        receipt,
    )


async def _invoke_pdf(
    app: FastAPI,
    settings: Settings,
    *,
    name: str,
    request: PDFIngestRequest | None = None,
    operation_id: uuid.UUID | None = None,
    explicit_resume: bool = False,
) -> dict[str, Any]:
    token = get_access_token()
    outcome: AuditResult
    async with app.state.mcp_session_factory() as session:
        try:
            if token is None:
                raise MCPAuthError("invalid_token", 401)
            artifacts = MCPArtifactService(
                session,
                settings,
                storage=getattr(app.state, "mcp_artifact_storage", None),
                security=getattr(app.state, "mcp_artifact_security", None),
            )
            if request is None and artifacts.security is None:
                artifacts.security = UploadSecurityService(
                    settings=settings,
                    session_factory=app.state.mcp_session_factory,
                )
            service = MCPPDFIngestionService(
                session,
                settings,
                ingestion_support(),
                artifacts=artifacts,
                document_storage=getattr(app.state, "mcp_document_storage", None),
            )
            if request is not None:
                principal = await MCPOperationService(session, settings)._authorize(
                    token.token, "mcp:upload"
                )
                result = await service.inspect(principal, request)
            else:
                assert operation_id is not None
                result = await service.execute(
                    access_token=token.token,
                    operation_id=operation_id,
                    explicit_resume=explicit_resume,
                )
            outcome = "success"
        except MCPAuthError:
            await session.rollback()
            outcome = "denied"
            result = {
                "error": "access_denied",
                "message": "The current connection does not authorize this ingestion.",
            }
        except (
            ArtifactError,
            MCPOperationError,
            HTTPException,
            ValidationError,
            ImageValidationError,
            DocumentParserUnavailableError,
            UnsupportedDocumentBatchFormatError,
            DocumentDistributionCapacityError,
            DBAPIError,
        ) as exc:
            await session.rollback()
            outcome = "blocked"
            result = {
                "error": "ingestion_unavailable",
                "message": "Inspect this upload and its operation. Reuse the original operation ID after a temporary failure; changed source or roster revisions require a newly inspected upload.",
            }
            if isinstance(exc, MCPOperationError) and exc.code == "ingestion_revision_changed":
                result["error"] = "ingestion_revision_changed"
            if (
                (isinstance(exc, ArtifactError) and exc.status_code == 503)
                or isinstance(exc, DBAPIError)
                and getattr(exc.orig, "sqlstate", None) == "55P03"
            ):
                result = {
                    "error": "ingestion_busy",
                    "message": "Source records or ingestion capacity are busy. Resume the same operation ID later.",
                }
        except Exception:
            await session.rollback()
            outcome = "failed"
            result = {
                "error": "ingestion_failed",
                "message": "Resume the same operation ID to recover its outcome. Do not submit another retry key for this upload.",
            }
        claims = token.claims if token and token.claims else {}
        audit = await AuditLogRepository(session).record(
            action=f"mcp.tool.{name}",
            entity_type="mcp_operation",
            entity_id=str(operation_id) if operation_id else None,
            user_id=uuid.UUID(token.subject) if token and token.subject else None,
            result=outcome,
            metadata={"capability": "mcp:upload", "connection_id": claims.get("grant_id")},
        )
        # Never compensate after an ambiguous COMMIT; the canonical draft may be durable.
        await session.commit()
        mark_invocation_audited()
        result.update(
            audit_id=str(audit.id),
            environment=settings.app_env,
            revision=settings.app_revision,
            observed_at=datetime.now(UTC).isoformat(),
            completeness="complete" if outcome == "success" else "unavailable",
        )
        if operation_id is not None:
            result.setdefault("operation_id", str(operation_id))
        return result


def register_pdf_ingestion_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    definition = pdf_ingestion_operation(settings, ingestion_support())
    app.state.mcp_operations[definition.policy.name] = definition

    @server.tool(
        meta={"capability": "mcp:upload"},
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
    )
    async def inspect_document_pdf_ingestion(upload: PDFIngestRequest) -> dict[str, Any]:
        """Inspect a staged PDF for one exact group and travel-document lane.

        Resolve missing agency, group or document type before ingestion. This
        returns the current passenger/source revision; it does not classify, save
        or approve a document. If already claimed, resume its operation ID.
        """
        return await _invoke_pdf(
            app, settings, name="inspect_document_pdf_ingestion", request=upload
        )

    @server.tool(
        meta={"capability": "mcp:upload"},
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def ingest_document_pdf(
        upload: PDFIngestRequest,
        expected_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")],
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Append the staged PDF through the existing travel-document workflow.

        Use the inspected revision and one stable retry key. The durable claim
        precedes bounded synchronous scan/classification and passenger matching.
        A retained draft and per-file receipt are returned; rejections remain
        reviewable. This never replaces documents, forces matches, approves types,
        saves drafts, sends messages or starts passport OCR. Original files remain.
        """
        receipt = await invoke_operation(
            app,
            settings,
            definition,
            idempotency_key=idempotency_key,
            payload={
                "upload": upload.model_dump(mode="json"),
                "expected_revision": expected_revision,
            },
        )
        if "receipt" not in receipt:
            return receipt
        result = await _invoke_pdf(
            app,
            settings,
            name="execute_document_pdf_ingestion",
            operation_id=uuid.UUID(receipt["receipt"]["operation_id"]),
        )
        result["receipt"] = receipt["receipt"]
        return result

    @server.tool(
        meta={"capability": "mcp:upload"},
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def resume_document_pdf_ingestion(operation_id: uuid.UUID) -> dict[str, Any]:
        """Explicitly resume a queued PDF ingestion or recover its retained draft.

        This can authorize a new connection for the same actor after current
        scope checks. Automatic execution remains bound to the original grant.
        A successful result is never rebuilt if its retained batch was removed.
        Temporary source expiry cannot delete a retained business document.
        """
        return await _invoke_pdf(
            app,
            settings,
            name="resume_document_pdf_ingestion",
            operation_id=operation_id,
            explicit_resume=True,
        )
