"""Tenant-scoped source queries for one bounded exact matching component."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    IdentityEvidenceValues,
    submission_identity_evidence,
)
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_match_evidence import (
    _canonical_search_corpus,
    _merge_evidence,
    _token_prefilter,
)
from app.infrastructure.repositories.passport_whatsapp_match_projection import (
    _submission_comparison,
    matching_field_keys_from_storage,
)


async def load_targeted_links(
    session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID, max_cluster_size: int
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, tuple[str, ...] | None]] | None:
    linked_rows = (
        await session.execute(
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
            .limit(max_cluster_size + 1)
        )
    ).all()
    if len(linked_rows) > max_cluster_size:
        return None
    linked_broadcasts = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name, _matching_fields in linked_rows
    }
    matching_fields_by_broadcast = {
        broadcast_id: matching_field_keys_from_storage(matching_fields)
        for broadcast_id, _broadcast_name, matching_fields in linked_rows
    }
    # The bounded SQL token prefilter was designed around the legacy identity
    # families. Explicit arbitrary fields can have shapes it cannot prove are
    # a complete superset, so fail closed to the authoritative full matcher.
    if any(value is not None for value in matching_fields_by_broadcast.values()):
        return None

    return linked_broadcasts, matching_fields_by_broadcast


async def load_targeted_seeds(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    seed_ids: tuple[uuid.UUID, ...],
    seed_phone_numbers: frozenset[str],
) -> tuple[
    dict[uuid.UUID, PassportSubmissionModel],
    dict[uuid.UUID, WhatsAppBroadcastRecipientModel],
    IdentityEvidenceValues,
]:
    seed_submissions = list(
        (
            await session.execute(
                select(PassportSubmissionModel).where(
                    PassportSubmissionModel.id.in_(seed_ids),
                    PassportSubmissionModel.group_id == group_id,
                    PassportSubmissionModel.agency_id == agency_id,
                    PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                )
            )
        ).scalars()
    )
    submission_models = {item.id: item for item in seed_submissions}
    recipient_models: dict[uuid.UUID, WhatsAppBroadcastRecipientModel] = {}
    evidence = IdentityEvidenceValues(phones=seed_phone_numbers)
    for submission in seed_submissions:
        evidence = _merge_evidence(
            evidence,
            submission_identity_evidence(_submission_comparison(submission)),
        )

    return submission_models, recipient_models, evidence


async def load_targeted_resolutions(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    submission_models: dict[uuid.UUID, PassportSubmissionModel],
    max_cluster_size: int,
) -> list[PassportRosterResolutionModel] | None:
    active_resolutions: list[PassportRosterResolutionModel] = []
    if submission_models:
        resolution_corpus = _canonical_search_corpus(
            PassportRosterResolutionModel.excluded_submission_ids
        )
        submission_uuid_tokens = tuple(sorted(item.hex.upper() for item in submission_models))
        active_resolutions = list(
            (
                await session.execute(
                    select(PassportRosterResolutionModel)
                    .where(
                        PassportRosterResolutionModel.client_group_id == group_id,
                        PassportRosterResolutionModel.agency_id == agency_id,
                        PassportRosterResolutionModel.status == "active",
                        or_(
                            PassportRosterResolutionModel.submission_id.in_(
                                tuple(submission_models)
                            ),
                            _token_prefilter(
                                resolution_corpus,
                                submission_uuid_tokens,
                            ),
                        ),
                    )
                    .limit(max_cluster_size + 1)
                )
            ).scalars()
        )
        if len(active_resolutions) > max_cluster_size:
            return None
    return active_resolutions
