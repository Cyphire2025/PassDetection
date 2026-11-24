"""Shared, tenant-scoped data loading for passport/WhatsApp matching."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    IdentityEvidenceValues,
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_comparison_cache import (
    PassportWhatsAppComparisonCache,
)
from app.infrastructure.repositories.passport_whatsapp_match_evidence import (
    _ascii_cluster_tokens as _build_cluster_tokens,
)
from app.infrastructure.repositories.passport_whatsapp_match_evidence import (
    _canonical_search_corpus as _canonical_search_corpus,
)
from app.infrastructure.repositories.passport_whatsapp_match_evidence import (
    _merge_evidence as _merge_evidence,
)
from app.infrastructure.repositories.passport_whatsapp_match_evidence import (
    _token_prefilter as _token_prefilter,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    SubmissionComparisonSource as SubmissionComparisonSource,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    TargetedPassportWhatsAppMatchContext as TargetedPassportWhatsAppMatchContext,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    _recipient_comparison as _recipient_comparison,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    _stored_uuid_list as _stored_uuid_list,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    _submission_comparison as _submission_comparison,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    matching_field_keys_from_storage as matching_field_keys_from_storage,
)
from app.infrastructure.repositories.passport_whatsapp_match_targeted import (
    load_targeted_match_context,
)

TARGETED_MATCH_CLUSTER_LIMIT = 64
_TARGETED_MATCH_TOKEN_LIMIT = 256
_TARGETED_MATCH_TOKEN_BYTES_LIMIT = 8192
_TARGETED_MATCH_MAX_ROUNDS = 8

recipient_comparison_from_model = _recipient_comparison
submission_comparison_from_model = _submission_comparison


def _ascii_cluster_tokens(evidence: IdentityEvidenceValues) -> tuple[str, ...] | None:
    return _build_cluster_tokens(
        evidence,
        token_limit=_TARGETED_MATCH_TOKEN_LIMIT,
        token_bytes_limit=_TARGETED_MATCH_TOKEN_BYTES_LIMIT,
    )


async def load_targeted_unresolved_passport_whatsapp_match_context(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    seed_submission_ids: tuple[uuid.UUID, ...],
    seed_phone_numbers: frozenset[str],
    max_cluster_size: int = TARGETED_MATCH_CLUSTER_LIMIT,
) -> TargetedPassportWhatsAppMatchContext | None:
    """Load one bounded component, or request authoritative full reconciliation."""
    return await load_targeted_match_context(
        session,
        group_id=group_id,
        agency_id=agency_id,
        seed_submission_ids=seed_submission_ids,
        seed_phone_numbers=seed_phone_numbers,
        max_cluster_size=max_cluster_size,
        max_rounds=_TARGETED_MATCH_MAX_ROUNDS,
        token_builder=_ascii_cluster_tokens,
        compare=compare_group_submissions,
    )


async def load_unresolved_passport_whatsapp_match_context(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    broadcast_group_ids: list[uuid.UUID] | tuple[uuid.UUID, ...] | None = None,
    comparison_cache: PassportWhatsAppComparisonCache | None = None,
) -> tuple[
    dict[uuid.UUID, str],
    list[WhatsAppBroadcastRecipientModel],
    list[PassportSubmissionModel],
    list[SubmissionMatchRow],
]:
    """Load and compare the unresolved roster for one passport group.

    Resolved replacement/rejection submissions and suppressed recipients are
    excluded so every caller uses the same current matching rules. Callers may
    scope the comparison to particular linked broadcasts; this keeps a global
    broadcast's Unidentified tab accurate when one passport group is linked to
    more than one broadcast.
    """

    linked_statement = (
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
            ClientGroupWhatsAppBroadcastLinkModel.matching_field_keys,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            WhatsAppBroadcastGroupModel.agency_id == agency_id,
        )
    )
    if broadcast_group_ids is not None:
        linked_statement = linked_statement.where(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id.in_(
                sorted(set(broadcast_group_ids), key=str)
            )
        )
    linked_result = await session.execute(linked_statement)
    linked_rows = linked_result.all()
    linked_broadcasts = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name, _matching_fields in linked_rows
    }
    matching_fields_by_broadcast = {
        broadcast_id: matching_field_keys_from_storage(matching_fields)
        for broadcast_id, _broadcast_name, matching_fields in linked_rows
    }

    resolution_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group_id,
            PassportRosterResolutionModel.agency_id == agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    active_resolutions = list(resolution_result.scalars().all())
    excluded_submission_ids = {
        submission_id
        for resolution in active_resolutions
        for submission_id in (
            [resolution.submission_id] + _stored_uuid_list(resolution.excluded_submission_ids)
        )
    }

    recipient_models: list[WhatsAppBroadcastRecipientModel] = []
    if linked_broadcasts:
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.agency_id == agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked_broadcasts)),
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
            )
        )
        recipient_models = list(recipient_result.scalars().all())

    submission_result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        )
    )
    submission_models = list(submission_result.scalars().all())

    recipient_values = [
        _recipient_comparison(
            recipient,
            linked_broadcasts,
            matching_fields_by_broadcast,
        )
        for recipient in recipient_models
    ]
    submission_values = [
        _submission_comparison(submission)
        for submission in submission_models
        if submission.id not in excluded_submission_ids
    ]
    # Large configurable rosters must not monopolize the API event loop. Only
    # materialized comparison values cross this boundary, never the async session.
    if comparison_cache is None:
        rows, _counts = await asyncio.to_thread(
            compare_group_submissions,
            recipient_values,
            submission_values,
        )
    else:
        rows = await comparison_cache.compare(
            agency_id=agency_id,
            group_id=group_id,
            recipients=recipient_values,
            submissions=submission_values,
        )
    return linked_broadcasts, recipient_models, submission_models, rows
