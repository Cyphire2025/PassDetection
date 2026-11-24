"""Bounded connected-component orchestration with authoritative full-match fallback."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    IdentityEvidenceValues,
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    SubmissionMatchSummary,
)
from app.infrastructure.database.models import (
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_match_evidence import (
    _canonical_search_corpus,
)
from app.infrastructure.repositories.passport_whatsapp_match_expansion import (
    expand_targeted_recipients,
    expand_targeted_submissions,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    TargetedPassportWhatsAppMatchContext,
    build_targeted_context,
)
from app.infrastructure.repositories.passport_whatsapp_match_sources import (
    load_targeted_links,
    load_targeted_resolutions,
    load_targeted_seeds,
)


async def load_targeted_match_context(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    seed_submission_ids: tuple[uuid.UUID, ...],
    seed_phone_numbers: frozenset[str],
    max_cluster_size: int,
    max_rounds: int,
    token_builder: Callable[[IdentityEvidenceValues], tuple[str, ...] | None],
    compare: Callable[
        [list[RecipientForComparison], list[SubmissionForComparison]],
        tuple[list[SubmissionMatchRow], SubmissionMatchSummary],
    ],
) -> TargetedPassportWhatsAppMatchContext | None:
    """Load one exact evidence component without materializing the whole group.

    ``None`` means completeness could not be proven within the fixed bound and
    the caller must use the authoritative full-group reconciler.  PostgreSQL is
    required for the compact JSON prefilter; other dialects also fail closed.
    """

    seed_ids = tuple(sorted(set(seed_submission_ids), key=str))
    if not seed_ids or len(seed_ids) > max_cluster_size:
        return None
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return None

    links = await load_targeted_links(
        session, group_id=group_id, agency_id=agency_id, max_cluster_size=max_cluster_size
    )
    if links is None:
        return None
    linked_broadcasts, matching_fields_by_broadcast = links
    submission_models, recipient_models, evidence = await load_targeted_seeds(
        session,
        group_id=group_id,
        agency_id=agency_id,
        seed_ids=seed_ids,
        seed_phone_numbers=seed_phone_numbers,
    )
    recipient_corpus = _canonical_search_corpus(
        WhatsAppBroadcastRecipientModel.normalized_phone_number,
        WhatsAppBroadcastRecipientModel.name,
        WhatsAppBroadcastRecipientModel.imported_fields,
    )
    submission_corpus = _canonical_search_corpus(
        PassportSubmissionModel.client_name,
        PassportSubmissionModel.client_phone,
        PassportSubmissionModel.family_head_phone,
        PassportSubmissionModel.client_email,
        PassportSubmissionModel.family_head_email,
        PassportSubmissionModel.confirmed_fields,
        PassportSubmissionModel.extracted_fields,
        PassportSubmissionModel.staff_metadata,
    )

    for _round in range(max_rounds):
        tokens = token_builder(evidence)
        if tokens is None:
            return None
        if not tokens:
            break
        recipient_result = await expand_targeted_recipients(
            session,
            agency_id=agency_id,
            linked_broadcasts=linked_broadcasts,
            matching_fields_by_broadcast=matching_fields_by_broadcast,
            recipient_models=recipient_models,
            evidence=evidence,
            recipient_corpus=recipient_corpus,
            tokens=tokens,
            max_cluster_size=max_cluster_size,
        )
        if recipient_result is None:
            return None
        recipient_changed, evidence = recipient_result
        submission_result = await expand_targeted_submissions(
            session,
            group_id=group_id,
            agency_id=agency_id,
            submission_models=submission_models,
            evidence=evidence,
            submission_corpus=submission_corpus,
            tokens=tokens,
            max_cluster_size=max_cluster_size,
        )
        if submission_result is None:
            return None
        submission_changed, evidence = submission_result
        if len(recipient_models) + len(submission_models) > max_cluster_size:
            return None
        if not (recipient_changed or submission_changed):
            break
    else:
        return None

    active_resolutions = await load_targeted_resolutions(
        session,
        group_id=group_id,
        agency_id=agency_id,
        submission_models=submission_models,
        max_cluster_size=max_cluster_size,
    )
    if active_resolutions is None:
        return None
    return build_targeted_context(
        linked_broadcasts=linked_broadcasts,
        matching_fields_by_broadcast=matching_fields_by_broadcast,
        submission_models=submission_models,
        recipient_models=recipient_models,
        active_resolutions=active_resolutions,
        seed_ids=seed_ids,
        evidence=evidence,
        compare=compare,
    )
