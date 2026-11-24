"""Durable email synchronization: document ingestion."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.email_integrations.matching import (
    GroupForAssociation,
    associate_group,
    associate_passenger,
)
from app.application.use_cases.email_integrations.relevance import has_group_context_evidence
from app.core.config.settings import Settings
from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import ClientGroupModel, DistributedDocumentModel
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import ClassifiedDocument
from app.infrastructure.email.pdf_validator import ValidatedEmailPdf
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository

from .sync_contracts import _SUPPORTED_PDF_TYPES, SyncClaim
from .sync_events import _advisory_transaction_lock, _record_event
from .sync_reviews import _ensure_artifact_review


async def _associate_and_route_document(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    message: EmailMessageModel,
    artifact: EmailArtifactModel,
    validated: ValidatedEmailPdf,
    classification: ClassifiedDocument,
    settings: Settings,
) -> list[str]:
    now = datetime.now(tz=UTC)
    owner = await UserRepository(session).get_by_id(claim.owner_user_id)
    if owner is None or not owner.is_active:
        artifact.processing_status = "review_required"
        artifact.error_code = "EMAIL_OWNER_UNAVAILABLE"
        artifact.error_message = "The mailbox owner is no longer active."
        return []
    groups_stmt = select(ClientGroupModel).where(
        ClientGroupModel.agency_id == claim.agency_id,
        ClientGroupModel.status.notin_({"archived", "deleted"}),
    )
    groups_result = await session.execute(
        AuthorizationPolicy.apply_group_visibility_scope(
            groups_stmt,
            owner,
        )
    )
    group_models = list(groups_result.scalars().all())
    passengers = await PassportSubmissionRepository(session).list_by_agency(
        claim.agency_id,
        limit=5_000,
        exclude_archived_groups=True,
        visible_to_user=owner,
    )
    group_association = associate_group(
        email_text=f"{message.subject or ''} {message.body_excerpt or ''}",
        document=classification,
        groups=[
            GroupForAssociation(
                id=group.id,
                name=group.name,
                token=group.token,
                destination=group.destination,
                travel_date=group.travel_date,
            )
            for group in group_models
        ],
        passengers=passengers,
    )
    group_passengers = (
        [passenger for passenger in passengers if passenger.group_id == group_association.group_id]
        if group_association.group_id
        else passengers
    )
    passenger_association = associate_passenger(
        document=classification,
        passengers=group_passengers,
    )
    stored_signals = message.evidence_json.get("signals", [])
    existing_signals = (
        [item for item in stored_signals if isinstance(item, str)]
        if isinstance(stored_signals, list)
        else []
    )
    has_roster_evidence = bool(
        group_association.candidate_group_ids
        or passenger_association.candidate_passenger_ids
        or has_group_context_evidence(existing_signals)
    )
    if not has_roster_evidence:
        artifact.processing_status = "ignored"
        artifact.processed_at = now
        artifact.error_code = None
        artifact.error_message = None
        return []

    group_id = group_association.group_id
    passenger_id = passenger_association.passenger_id
    artifact.group_id = group_id
    artifact.passenger_id = passenger_id
    artifact.match_confidence = min(
        group_association.confidence,
        passenger_association.confidence,
    )
    message.group_id = group_id

    evidence = tuple(
        dict.fromkeys(
            [
                *group_association.evidence,
                *passenger_association.evidence,
                f"document_type_{classification.detected_type}",
            ]
        )
    )
    message.relevance_status = (
        "relevant" if classification.detected_type in _SUPPORTED_PDF_TYPES else "possible"
    )
    message.relevance_confidence = max(
        message.relevance_confidence or 0.0,
        0.94 if classification.detected_type in _SUPPORTED_PDF_TYPES else 0.5,
    )
    message.evidence_json = {"signals": list(dict.fromkeys([*existing_signals, *evidence]))}

    if classification.detected_type == "passport":
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="passenger_match",
            proposed_action="route_passport_manually",
            confidence=artifact.match_confidence or 0.0,
            evidence=(*evidence, "passport_requires_gemini_upload_workflow"),
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
        )
        return []

    if classification.detected_type not in _SUPPORTED_PDF_TYPES:
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="relevance",
            proposed_action="classify_document",
            confidence=artifact.match_confidence or 0.0,
            evidence=evidence,
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
        )
        return []

    if group_id is None or group_association.status != "matched":
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="group_match",
            proposed_action="assign_group",
            confidence=group_association.confidence,
            evidence=evidence,
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
            alternatives=[
                {"group_id": str(group_id)} for group_id in group_association.candidate_group_ids
            ],
        )
        return []

    if passenger_id is None or passenger_association.status != "matched":
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="passenger_match",
            proposed_action="assign_passenger",
            confidence=passenger_association.confidence,
            evidence=evidence,
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
            alternatives=[
                {"passenger_id": str(passenger_id)}
                for passenger_id in passenger_association.candidate_passenger_ids
            ],
        )
        return []

    await _advisory_transaction_lock(
        session,
        (
            f"email-document:{claim.agency_id}:{group_id}:"
            f"{passenger_id}:{classification.detected_type}"
        ),
    )
    existing_document = await session.scalar(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.agency_id == claim.agency_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.passenger_id == passenger_id,
            DistributedDocumentModel.document_type == classification.detected_type,
        )
        .order_by(DistributedDocumentModel.created_at.desc())
        .limit(1)
    )
    if existing_document is not None:
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="possible_revision",
            proposed_action="confirm_revision",
            confidence=artifact.match_confidence or 0.0,
            evidence=(*evidence, "existing_passenger_document"),
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
            conflicts=[{"existing_document_id": str(existing_document.id)}],
        )
        return []

    if not settings.email_auto_actions_enabled:
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="passenger_match",
            proposed_action="confirm_new_document",
            confidence=artifact.match_confidence or 0.0,
            evidence=(*evidence, "auto_actions_disabled"),
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
        )
        return []

    canonical_keys = await _ingest_confirmed_artifact(
        session,
        claim=claim,
        message=message,
        artifact=artifact,
        validated=validated,
        document_type=classification.detected_type,
        group_id=group_id,
        passenger_id=passenger_id,
        created_by_user_id=None,
        actor_email=None,
        result_type="created",
    )
    artifact.processing_status = "completed"
    artifact.processed_at = now
    return canonical_keys


async def _ingest_confirmed_artifact(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    message: EmailMessageModel,
    artifact: EmailArtifactModel,
    validated: ValidatedEmailPdf,
    document_type: str,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None,
    actor_email: str | None,
    result_type: str,
) -> list[str]:
    passengers = await PassportSubmissionRepository(session).list_by_group(
        claim.agency_id,
        group_id,
        limit=5_000,
        exclude_archived_groups=True,
    )
    result = await TravelDocumentIngestionService(session).ingest(
        agency_id=claim.agency_id,
        group_id=group_id,
        document_type=document_type,
        passengers=passengers,
        files=[
            TravelDocumentFile(
                filename=validated.filename,
                content=validated.content,
                content_type=validated.content_type,
            )
        ],
        created_by_user_id=created_by_user_id,
        actor_email=actor_email,
        forced_passenger_id=passenger_id,
        audit_source="email_integration",
        storage_prefix=(
            f"email-integrations-canonical/{claim.agency_id}/{message.id}/{artifact.id}"
        ),
    )
    if not result.documents:
        reason = (
            result.rejected[0].reason
            if result.rejected
            else "The selected file did not produce a travel document"
        )
        raise ValueError(reason)
    saved_at = datetime.now(tz=UTC)
    result.batch.status = "saved"
    result.batch.saved_at = saved_at
    result.batch.updated_at = saved_at
    canonical_keys = list(dict.fromkeys(document.storage_key for document in result.documents))
    try:
        for document in result.documents:
            session.add(
                EmailArtifactDocumentModel(
                    id=uuid.uuid4(),
                    agency_id=claim.agency_id,
                    owner_user_id=claim.owner_user_id,
                    artifact_id=artifact.id,
                    distributed_document_id=document.id,
                    result_type=result_type,
                    match_confidence=artifact.match_confidence,
                    match_evidence={
                        "source": "email_integration",
                        "human_confirmed": created_by_user_id is not None,
                    },
                    created_at=datetime.now(tz=UTC),
                )
            )
        await _record_event(
            session,
            connection_id=claim.connection_id,
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            message_id=message.id,
            artifact_id=artifact.id,
            event_type="document_added",
            stage="success",
            summary_code="EMAIL_DOCUMENT_ADDED",
            details={
                "document_type": document_type,
                "document_count": len(result.documents),
            },
            actor_type="user" if created_by_user_id else "system",
            actor_user_id=created_by_user_id,
            changed_entity_type="passport_submission",
            changed_entity_id=passenger_id,
        )
    except Exception:
        await MinioStorageRepository().delete_files(canonical_keys)
        raise
    return canonical_keys
