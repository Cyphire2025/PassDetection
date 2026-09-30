"""Synthetic retained mailbox cohorts for canonical summary component tests."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    UserModel,
)

PER_COHORT = dict(connected_accounts=3, relevant_emails_today=2, documents_retrieved_today=1,
    automatically_matched_today=1, revisions_detected_today=3, pending_review=2, retrieval_failures_today=1)


async def seed_email_overview(session, actor, *, today=None, opaque_size=1024):
    today = today or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    before, future = today - timedelta(microseconds=1), today + timedelta(days=1)
    agencies = [AgencyModel(id=uuid.uuid4(), name=f"Mailbox agency {i}", email=f"{uuid.uuid4()}@example.test",
        is_active=bool(i)) for i in range(2)]
    other = UserModel(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.test", full_name="Other owner",
        hashed_password="SECRET_PASSWORD", role="super_admin", is_active=True)
    session.add_all([*agencies, other])
    await session.flush()
    cohorts = []
    for owner, agency in [(actor, agencies[0]), (actor, agencies[1]), (other, agencies[0])]:
        common = dict(agency_id=agency.id, owner_user_id=owner.id)
        connections = [EmailConnectionModel(id=uuid.uuid4(), **common, provider="gmail",
            provider_account_id="SECRET_PROVIDER_" + uuid.uuid4().hex,
            email_address=f"{uuid.uuid4()}@private.example.test", status=status,
            disconnected_at=today if status == "disconnected" else None,
            access_token_ciphertext=b"SECRET_ACCESS", refresh_token_ciphertext=b"SECRET_REFRESH",
            sync_cursor="SECRET_SYNC_CURSOR", last_error_message="SECRET_ERROR")
            for status in ("pending", "active", "failing", "paused", "expired", "disconnecting", "disconnected")]
        session.add_all(connections)
        await session.flush()
        messages = [EmailMessageModel(id=uuid.uuid4(), **common, connection_id=connections[1].id,
            provider_message_id="SECRET_MESSAGE_" + uuid.uuid4().hex, subject="PRIVATE_SUBJECT",
            body_excerpt="SECRET_BODY", received_at=stamp, relevance_status=relevance)
            for stamp, relevance in [(before, "relevant"), (today, "relevant"), (future, "relevant"), (today, "ignored")]]
        session.add_all(messages)
        await session.flush()
        artifacts = [EmailArtifactModel(id=uuid.uuid4(), **common, message_id=messages[1].id,
            provider_artifact_id="SECRET_ARTIFACT_" + uuid.uuid4().hex, kind="attachment", filename="PRIVATE_FILE.pdf",
            storage_key="SECRET_STORAGE", source_url_ciphertext=b"SECRET_URL", source_url_encryption_key_version=1,
            retrieval_status=status, retrieved_at=retrieved, last_error_at=error_at, error_message="SECRET_ERROR")
            for status, retrieved, error_at in [("retrieved", before, None), ("retrieved", today, None),
                ("failed", None, today), ("failed", None, before)]]
        session.add_all(artifacts)
        group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Synthetic", token=uuid.uuid4().hex)
        session.add(group)
        await session.flush()
        batch = DocumentDistributionBatchModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id, document_type="visa")
        session.add(batch)
        await session.flush()
        for evidence, stamp in [({"human_confirmed": False, "unknown": "SECRET" + "x" * opaque_size}, today),
                ({"human_confirmed": True}, today), ({}, today), ({"human_confirmed": None}, today),
                ({"human_confirmed": False}, before)]:
            document = DistributedDocumentModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
                batch_id=batch.id, document_type="visa", original_filename="PRIVATE_FILE.pdf", storage_key="SECRET_DOC")
            session.add(document)
            await session.flush()
            session.add(EmailArtifactDocumentModel(id=uuid.uuid4(), **common, artifact_id=artifacts[1].id,
                distributed_document_id=document.id, result_type="created", match_evidence=evidence, created_at=stamp))
        reviews = [EmailReviewItemModel(id=uuid.uuid4(), **common, message_id=messages[1].id,
            artifact_id=artifacts[index % 4].id, review_type=kind, status=status, proposed_action="review",
            evidence={"secret": "SECRET_REVIEW"}, proposed_payload={"secret": "SECRET_PAYLOAD"}, created_at=stamp,
            deferred_until=future if status == "deferred" else None,
            resolved_at=today if status in {"resolved", "rejected", "cancelled"} else None)
            for index, (kind, status, stamp) in enumerate([("possible_revision", "open", today),
                ("possible_revision", "deferred", today), ("possible_revision", "resolved", before),
                ("relevance", "rejected", today), ("possible_revision", "cancelled", today)])]
        session.add_all(reviews)
        await session.flush()
        cohorts.append(SimpleNamespace(owner_id=owner.id, agency_id=agency.id, connections=connections,
            messages=messages, artifacts=artifacts, reviews=reviews))
    return SimpleNamespace(agencies=agencies, other=other, cohorts=cohorts, today=today,
        expected={name: 2 * count for name, count in PER_COHORT.items()})
