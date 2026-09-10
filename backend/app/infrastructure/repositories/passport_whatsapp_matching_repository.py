"""Shared, tenant-scoped data loading for passport/WhatsApp matching."""

from __future__ import annotations

import asyncio
import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.use_cases.whatsapp.group_submission_matching import (
    IdentityEvidenceValues,
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    compare_group_submissions,
    recipient_identity_evidence,
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

TARGETED_MATCH_CLUSTER_LIMIT = 64
_TARGETED_MATCH_TOKEN_LIMIT = 256
_TARGETED_MATCH_TOKEN_BYTES_LIMIT = 8192
_TARGETED_MATCH_MAX_ROUNDS = 8


class SubmissionComparisonSource(Protocol):
    """Common persisted/domain submission surface used by identity matching."""

    @property
    def id(self) -> uuid.UUID: ...

    @property
    def client_name(self) -> str: ...

    @property
    def client_phone(self) -> str | None: ...

    @property
    def family_head_phone(self) -> str | None: ...

    @property
    def updated_at(self) -> datetime: ...

    @property
    def client_email(self) -> str | None: ...

    @property
    def family_head_email(self) -> str | None: ...

    @property
    def confirmed_fields(self) -> Mapping[str, object] | None: ...

    @property
    def extracted_fields(self) -> Mapping[str, object] | None: ...

    @property
    def staff_metadata(self) -> Mapping[str, object] | None: ...

    @property
    def custom_answers(self) -> Sequence[Mapping[str, object]]: ...

    @property
    def custom_detail_answers(self) -> Sequence[Mapping[str, object]]: ...

    @property
    def departure_city(self) -> str | None: ...

    @property
    def nearest_domestic_airport(self) -> str | None: ...

    @property
    def family_relation(self) -> str | None: ...

    @property
    def family_gender(self) -> str | None: ...

    @property
    def family_head_name(self) -> str | None: ...


def matching_field_keys_from_storage(value: object) -> tuple[str, ...] | None:
    """Decode nullable link policy while failing closed on malformed JSON."""

    if value is None:
        return None
    if (
        not isinstance(value, list)
        or not value
        or any(
            not isinstance(item, str) or re.fullmatch(r"[a-z0-9_]{1,64}", item) is None
            for item in value
        )
    ):
        return ()
    return tuple(dict.fromkeys(value))


@dataclass(frozen=True, slots=True)
class TargetedPassportWhatsAppMatchContext:
    """A proven-complete, bounded matching connected component."""

    linked_broadcasts: dict[uuid.UUID, str]
    recipients: tuple[WhatsAppBroadcastRecipientModel, ...]
    submissions: tuple[PassportSubmissionModel, ...]
    rows: tuple[SubmissionMatchRow, ...]
    affected_submission_ids: frozenset[uuid.UUID]
    affected_phone_numbers: frozenset[str]


def _stored_uuid_list(values: object) -> list[uuid.UUID]:
    if not isinstance(values, list):
        return []
    parsed: list[uuid.UUID] = []
    for value in values:
        try:
            parsed.append(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return parsed


def _recipient_comparison(
    recipient: WhatsAppBroadcastRecipientModel,
    linked_broadcasts: dict[uuid.UUID, str],
    matching_fields_by_broadcast: dict[uuid.UUID, tuple[str, ...] | None] | None = None,
) -> RecipientForComparison:
    return RecipientForComparison(
        id=recipient.id,
        broadcast_id=recipient.broadcast_group_id,
        broadcast_name=linked_broadcasts[recipient.broadcast_group_id],
        name=recipient.name,
        phone=recipient.normalized_phone_number,
        updated_at=recipient.created_at,
        imported_fields=dict(recipient.imported_fields or {}),
        matching_field_keys=(matching_fields_by_broadcast or {}).get(recipient.broadcast_group_id),
    )


def _submission_comparison(
    submission: SubmissionComparisonSource,
) -> SubmissionForComparison:
    return SubmissionForComparison(
        id=submission.id,
        name=submission.client_name,
        client_phone=submission.client_phone,
        family_head_phone=submission.family_head_phone,
        updated_at=submission.updated_at,
        client_email=submission.client_email,
        family_head_email=submission.family_head_email,
        confirmed_fields=dict(submission.confirmed_fields or {}),
        extracted_fields=dict(submission.extracted_fields or {}),
        staff_metadata=dict(submission.staff_metadata or {}),
        custom_answers=tuple(getattr(submission, "custom_answers", None) or ()),
        custom_detail_answers=tuple(getattr(submission, "custom_detail_answers", None) or ()),
        departure_city=getattr(submission, "departure_city", None),
        nearest_domestic_airport=getattr(
            submission,
            "nearest_domestic_airport",
            None,
        ),
        family_relation=getattr(submission, "family_relation", None),
        family_gender=getattr(submission, "family_gender", None),
        family_head_name=getattr(submission, "family_head_name", None),
    )


# Shared model-to-domain projections used by delivery/read paths that must use
# exactly the same evidence policy as the authoritative repository loaders.
recipient_comparison_from_model = _recipient_comparison
submission_comparison_from_model = _submission_comparison


def _merge_evidence(
    current: IdentityEvidenceValues,
    incoming: IdentityEvidenceValues,
) -> IdentityEvidenceValues:
    selected_fields: dict[str, frozenset[str]] = {
        key: frozenset(values) for key, values in current.selected_fields.items()
    }
    for key, values in incoming.selected_fields.items():
        selected_fields[key] = selected_fields.get(key, frozenset()) | values
    return IdentityEvidenceValues(
        phones=current.phones | incoming.phones,
        emails=current.emails | incoming.emails,
        passport_numbers=current.passport_numbers | incoming.passport_numbers,
        staff_codes=current.staff_codes | incoming.staff_codes,
        names=current.names | incoming.names,
        selected_fields=selected_fields,
    )


def _ascii_cluster_tokens(
    evidence: IdentityEvidenceValues,
) -> tuple[str, ...] | None:
    """Build the PostgreSQL prefilter tokens, or fail closed for non-ASCII data."""

    tokens: set[str] = set()
    for value in evidence.all_values:
        compatible = unicodedata.normalize("NFKC", value)
        if not compatible.isascii():
            return None
        compact = "".join(character for character in compatible.upper() if character.isalnum())
        if len(compact) < 2:
            return None
        tokens.add(compact)
    # The canonical phone normalizer expands a bare 10-digit Indian number to
    # +91.  The stored source value can therefore lack the prefix even though
    # its exact comparison value includes it; include both safe prefilter
    # forms. Exact Python evidence intersection still decides membership.
    for phone in evidence.phones:
        digits = "".join(character for character in phone if character.isdigit())
        if digits.startswith("91") and len(digits) == 12:
            tokens.add(digits[2:])
    if len(tokens) > _TARGETED_MATCH_TOKEN_LIMIT:
        return None
    ordered = tuple(sorted(tokens))
    if sum(len(token) for token in ordered) > _TARGETED_MATCH_TOKEN_BYTES_LIMIT:
        return None
    return ordered


def _canonical_search_corpus(*columns: object) -> ColumnElement[str]:
    # Targeted matching is enabled only on PostgreSQL.  Compacting the corpus
    # makes the SQL prefilter a superset of the exact Python normalizers; exact
    # intersections below discard false positives before they enter the graph.
    joined = func.concat_ws(
        "|",
        *(func.coalesce(cast(column, Text), "") for column in columns),
    )
    return func.regexp_replace(func.upper(joined), "[^A-Z0-9]+", "", "g")


def _token_prefilter(
    corpus: ColumnElement[str],
    tokens: tuple[str, ...],
) -> ColumnElement[bool]:
    # Tokens contain only A-Z/0-9, so one alternation is safe and avoids
    # repeating the relatively expensive canonicalization expression once per
    # evidence value.
    return corpus.op("~")("(" + "|".join(tokens) + ")")


async def load_targeted_unresolved_passport_whatsapp_match_context(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    seed_submission_ids: tuple[uuid.UUID, ...],
    seed_phone_numbers: frozenset[str],
    max_cluster_size: int = TARGETED_MATCH_CLUSTER_LIMIT,
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

    for _round in range(_TARGETED_MATCH_MAX_ROUNDS):
        tokens = _ascii_cluster_tokens(evidence)
        if tokens is None:
            return None
        if not tokens:
            break
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

        if len(recipient_models) + len(submission_models) > max_cluster_size:
            return None
        if not changed:
            break
    else:
        return None

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
    excluded_submission_ids = {
        submission_id
        for resolution in active_resolutions
        for submission_id in (
            [resolution.submission_id] + _stored_uuid_list(resolution.excluded_submission_ids)
        )
    }

    recipients = tuple(sorted(recipient_models.values(), key=lambda item: str(item.id)))
    submissions = tuple(sorted(submission_models.values(), key=lambda item: str(item.id)))
    recipient_values = [
        _recipient_comparison(
            recipient,
            linked_broadcasts,
            matching_fields_by_broadcast,
        )
        for recipient in recipients
    ]
    submission_values = [
        _submission_comparison(submission)
        for submission in submissions
        if submission.id not in excluded_submission_ids
    ]
    rows, _counts = compare_group_submissions(recipient_values, submission_values)
    return TargetedPassportWhatsAppMatchContext(
        linked_broadcasts=linked_broadcasts,
        recipients=recipients,
        submissions=submissions,
        rows=tuple(rows),
        affected_submission_ids=frozenset(seed_ids) | frozenset(submission_models),
        affected_phone_numbers=evidence.phones,
    )


async def load_unresolved_passport_whatsapp_match_context(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    broadcast_group_ids: list[uuid.UUID] | tuple[uuid.UUID, ...] | None = None,
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
    rows, _counts = await asyncio.to_thread(
        compare_group_submissions,
        recipient_values,
        submission_values,
    )
    return linked_broadcasts, recipient_models, submission_models, rows
