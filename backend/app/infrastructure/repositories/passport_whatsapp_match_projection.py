"""Persisted-model projections shared by exact passport/WhatsApp matching."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.application.use_cases.whatsapp.group_submission_matching import (
    IdentityEvidenceValues,
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    SubmissionMatchSummary,
)
from app.application.use_cases.whatsapp.imported_broadcast_phone import (
    has_public_collection_contact,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)


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
        has_public_collection_contact=has_public_collection_contact(submission),
    )


# Retain the original public type and serialization identities.
SubmissionComparisonSource.__module__ = (
    "app.infrastructure.repositories.passport_whatsapp_matching_repository"
)
TargetedPassportWhatsAppMatchContext.__module__ = (
    "app.infrastructure.repositories.passport_whatsapp_matching_repository"
)


def build_targeted_context(
    *,
    linked_broadcasts: dict[uuid.UUID, str],
    matching_fields_by_broadcast: dict[uuid.UUID, tuple[str, ...] | None],
    submission_models: dict[uuid.UUID, PassportSubmissionModel],
    recipient_models: dict[uuid.UUID, WhatsAppBroadcastRecipientModel],
    active_resolutions: list[PassportRosterResolutionModel],
    seed_ids: tuple[uuid.UUID, ...],
    evidence: IdentityEvidenceValues,
    compare: Callable[
        [list[RecipientForComparison], list[SubmissionForComparison]],
        tuple[list[SubmissionMatchRow], SubmissionMatchSummary],
    ],
) -> TargetedPassportWhatsAppMatchContext:
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
    rows, _counts = compare(recipient_values, submission_values)
    return TargetedPassportWhatsAppMatchContext(
        linked_broadcasts=linked_broadcasts,
        recipients=recipients,
        submissions=submissions,
        rows=tuple(rows),
        affected_submission_ids=frozenset(seed_ids) | frozenset(submission_models),
        affected_phone_numbers=evidence.phones,
    )
