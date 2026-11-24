"""One bounded evidence-expansion round, retaining exact query/merge order."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.use_cases.whatsapp.group_submission_matching import (
    IdentityEvidenceValues,
    recipient_identity_evidence,
    submission_identity_evidence,
)
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_match_evidence import (
    _merge_evidence,
    _token_prefilter,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    _recipient_comparison,
    _submission_comparison,
)


async def expand_targeted_recipients(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    linked_broadcasts: dict[uuid.UUID, str],
    matching_fields_by_broadcast: dict[uuid.UUID, tuple[str, ...] | None],
    recipient_models: dict[uuid.UUID, WhatsAppBroadcastRecipientModel],
    evidence: IdentityEvidenceValues,
    recipient_corpus: ColumnElement[str],
    tokens: tuple[str, ...],
    max_cluster_size: int,
) -> tuple[bool, IdentityEvidenceValues] | None:
    changed = False
    if linked_broadcasts:
        recipient_statement = select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.agency_id == agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(tuple(linked_broadcasts)),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
            _token_prefilter(recipient_corpus, tokens),
        )
        if recipient_models:
            recipient_statement = recipient_statement.where(
                WhatsAppBroadcastRecipientModel.id.not_in(tuple(recipient_models))
            )
        recipient_candidates = list(
            (await session.execute(recipient_statement.limit(max_cluster_size + 1))).scalars()
        )
        if len(recipient_candidates) > max_cluster_size:
            return None
        for recipient in recipient_candidates:
            comparison = _recipient_comparison(
                recipient,
                linked_broadcasts,
                matching_fields_by_broadcast,
            )
            recipient_evidence = recipient_identity_evidence((comparison,))
            if not (recipient_evidence.all_values & evidence.all_values):
                continue
            recipient_models[recipient.id] = recipient
            evidence = _merge_evidence(evidence, recipient_evidence)
            changed = True

    return changed, evidence


async def expand_targeted_submissions(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    submission_models: dict[uuid.UUID, PassportSubmissionModel],
    evidence: IdentityEvidenceValues,
    submission_corpus: ColumnElement[str],
    tokens: tuple[str, ...],
    max_cluster_size: int,
) -> tuple[bool, IdentityEvidenceValues] | None:
    changed = False
    submission_statement = select(PassportSubmissionModel).where(
        PassportSubmissionModel.group_id == group_id,
        PassportSubmissionModel.agency_id == agency_id,
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        _token_prefilter(submission_corpus, tokens),
    )
    if submission_models:
        submission_statement = submission_statement.where(
            PassportSubmissionModel.id.not_in(tuple(submission_models))
        )
    submission_candidates = list(
        (await session.execute(submission_statement.limit(max_cluster_size + 1))).scalars()
    )
    if len(submission_candidates) > max_cluster_size:
        return None
    for submission in submission_candidates:
        submission_evidence = submission_identity_evidence(_submission_comparison(submission))
        if not (submission_evidence.all_values & evidence.all_values):
            continue
        submission_models[submission.id] = submission
        evidence = _merge_evidence(evidence, submission_evidence)
        changed = True

    return changed, evidence
