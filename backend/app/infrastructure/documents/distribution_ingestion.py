"""Shared ingestion path for group-scoped travel documents.

Both dashboard uploads and background integrations use this service so file
classification, passenger matching, storage, persistence, and audit behavior
cannot drift into separate pipelines.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
)
from app.infrastructure.documents.document_matcher import (
    DOCUMENT_TYPES,
    ClassifiedDocument,
    DocumentMatcher,
    MatchResult,
    PassengerIdentifier,
    classify_documents_bounded,
)
from app.infrastructure.documents.storage_cleanup import persist_storage_cleanup_job
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class TravelDocumentFile:
    """One already-bounded file offered to the distribution workflow."""

    filename: str
    content: bytes
    content_type: str = "application/pdf"


@dataclass(frozen=True)
class RejectedTravelDocument:
    filename: str
    detected_type: str
    reason: str


@dataclass
class TravelDocumentIngestionResult:
    batch: DocumentDistributionBatchModel
    documents: list[DistributedDocumentModel] = field(default_factory=list)
    rejected: list[RejectedTravelDocument] = field(default_factory=list)
    created_storage_keys: tuple[str, ...] = ()


class TravelDocumentIngestionService:
    """Persist a document-distribution batch through the canonical matcher."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        matcher: DocumentMatcher | None = None,
        storage: MinioStorageRepository | None = None,
    ) -> None:
        self._session = session
        self._matcher = matcher or DocumentMatcher()
        self._storage = storage or MinioStorageRepository()

    async def ingest(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        document_type: str,
        passengers: list[PassportSubmission],
        files: list[TravelDocumentFile],
        created_by_user_id: uuid.UUID | None,
        actor_email: str | None,
        forced_passenger_id: uuid.UUID | None = None,
        audit_source: str = "dashboard_upload",
        storage_prefix: str | None = None,
        supplemental_identifiers: tuple[PassengerIdentifier, ...] = (),
        isolate_pdf_parsing: bool = False,
        before_persistence: (
            Callable[[], Awaitable[tuple[uuid.UUID | None, str | None] | None]] | None
        ) = None,
    ) -> TravelDocumentIngestionResult:
        if document_type not in DOCUMENT_TYPES:
            raise ValueError("Unsupported document type")
        if forced_passenger_id is not None and all(
            passenger.id != forced_passenger_id for passenger in passengers
        ):
            raise ValueError("The confirmed passenger is not part of this group")

        classifications = await asyncio.to_thread(
            classify_documents_bounded,
            self._matcher,
            [(file.filename, file.content, document_type) for file in files],
            isolate_pdf_parsing=isolate_pdf_parsing,
        )
        accepted: list[tuple[TravelDocumentFile, ClassifiedDocument]] = []
        rejected: list[RejectedTravelDocument] = []
        for file, classification in zip(files, classifications, strict=True):
            if not classification.accepted:
                rejected.append(
                    RejectedTravelDocument(
                        filename=file.filename,
                        detected_type=classification.detected_type,
                        reason=classification.reason,
                    )
                )
                continue
            accepted.append((file, classification))

        now = datetime.now(tz=UTC)
        batch = DocumentDistributionBatchModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
            status="draft",
            uploaded_count=0,
            rejected_count=len(rejected),
            matched_count=0,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        if forced_passenger_id is None:
            match_index = await asyncio.to_thread(
                self._matcher.build_index,
                passengers,
                agency_id=agency_id,
                group_id=group_id,
                supplemental_identifiers=supplemental_identifiers,
            )
            document_matches = await asyncio.to_thread(
                lambda: [
                    self._matcher.match_all(classification, passengers, index=match_index)
                    for _, classification in accepted
                ]
            )
        else:
            document_matches = [
                [
                    MatchResult(
                        passenger_id=forced_passenger_id,
                        confidence=1.0,
                        status="matched",
                        reason="Passenger confirmed during human review",
                    )
                ]
                for _ in accepted
            ]

        documents: list[DistributedDocumentModel] = []
        uploaded_keys: list[str] = []
        normalized_storage_prefix = (
            storage_prefix.strip().strip("/") if storage_prefix is not None else None
        )
        if storage_prefix is not None and not normalized_storage_prefix:
            raise ValueError("A non-empty storage prefix is required")
        try:
            for (file, classification), matches in zip(
                accepted,
                document_matches,
            ):
                storage_document_id = uuid.uuid4()
                object_namespace = normalized_storage_prefix or (
                    f"document-distribution/{group_id}/{batch.id}"
                )
                key = f"{object_namespace}/{storage_document_id}-{_safe_filename(file.filename)}"
                # Claim the deterministic key before the network call. If the
                # upload reaches storage but its acknowledgement is lost, the
                # failure path still knows which key it owns and may clean it.
                uploaded_keys.append(key)
                await self._storage.upload_file(
                    file.content,
                    key,
                    file.content_type or "application/pdf",
                )
                for match in matches:
                    model = DistributedDocumentModel(
                        id=uuid.uuid4(),
                        batch_id=batch.id,
                        agency_id=agency_id,
                        group_id=group_id,
                        passenger_id=match.passenger_id,
                        document_type=document_type,
                        original_filename=file.filename,
                        storage_key=key,
                        content_type=file.content_type or "application/pdf",
                        detected_type=classification.detected_type,
                        match_status=match.status,
                        match_confidence=match.confidence,
                        match_reason=(
                            "Shared PDF matched "
                            f"{len(matches)} passenger"
                            f"{'' if len(matches) == 1 else 's'}"
                            if len(matches) > 1 and match.status == "matched"
                            else match.reason
                        ),
                        extracted_name=classification.extracted_name,
                        extracted_passport_number=(classification.extracted_passport_number),
                        extracted_reference=classification.extracted_reference,
                        created_at=now,
                        updated_at=now,
                    )
                    documents.append(model)
        except Exception:
            # Object storage and the relational transaction are not atomic.
            # Remove only objects created by this failed invocation.
            await self._cleanup_owned_storage(
                uploaded_keys,
                agency_id=agency_id,
                batch_id=batch.id,
                durable=isolate_pdf_parsing,
            )
            raise

        try:
            if before_persistence is not None:
                refreshed_actor = await before_persistence()
                if refreshed_actor is not None:
                    created_by_user_id, actor_email = refreshed_actor
                    batch.created_by_user_id = created_by_user_id
            batch.uploaded_count = len(documents)
            batch.matched_count = sum(
                1 for document in documents if document.match_status == "matched"
            )
            self._session.add(batch)
            for document in documents:
                self._session.add(document)
            await AuditLogRepository(self._session).record(
                action="document_distribution_uploaded",
                entity_type="client_group",
                entity_id=str(group_id),
                agency_id=agency_id,
                user_id=created_by_user_id,
                actor_email=actor_email,
                metadata={
                    "document_type": document_type,
                    "uploaded_count": batch.uploaded_count,
                    "rejected_count": batch.rejected_count,
                    "matched_count": batch.matched_count,
                    "source": audit_source,
                },
            )
            # Surface relational constraint errors while object-storage
            # compensation is still in scope.
            await self._session.flush()
        except Exception:
            await self._session.rollback()
            await self._cleanup_owned_storage(
                uploaded_keys,
                agency_id=agency_id,
                batch_id=batch.id,
                durable=isolate_pdf_parsing,
            )
            raise
        return TravelDocumentIngestionResult(
            batch=batch,
            documents=documents,
            rejected=rejected,
            created_storage_keys=tuple(uploaded_keys),
        )

    async def _cleanup_owned_storage(
        self,
        storage_keys: list[str],
        *,
        agency_id: uuid.UUID,
        batch_id: uuid.UUID,
        durable: bool,
    ) -> None:
        if not storage_keys:
            return
        try:
            await self._storage.delete_files(storage_keys)
        except Exception:
            logger.warning(
                "document_distribution_storage_cleanup_deferred",
                object_count=len(storage_keys),
            )
            if durable:
                try:
                    await persist_storage_cleanup_job(
                        agency_id=agency_id,
                        source="document_distribution_compensation",
                        context_id=str(batch_id),
                        storage_keys=storage_keys,
                    )
                except Exception as exc:
                    logger.error(
                        "document_distribution_cleanup_tracking_failed",
                        batch_id=str(batch_id),
                        object_count=len(storage_keys),
                        error_type=type(exc).__name__,
                    )


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:120]
    return name or "document.pdf"
