"""Discover and resolve safe room-allocation priority fields."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    recipient_comparison_from_model,
    submission_comparison_from_model,
)

from .priority_context_fields import imported_priority_fields, selected_priority_fields
from .priority_context_sources import load_priority_broadcasts, load_priority_recipients
from .priority_field_catalog import _base_field_definitions as _base_field_definitions
from .priority_field_catalog import _deduplicate_labels as _deduplicate_labels
from .priority_field_catalog import _humanize_imported_field_label as _humanize_imported_field_label
from .priority_field_catalog import _metadata_field_definitions as _metadata_field_definitions
from .priority_field_policy import _NON_GROUPABLE_FIELD_KEYS as _NON_GROUPABLE_FIELD_KEYS
from .priority_field_policy import (
    _UNAVAILABLE_COMPACT_PRIORITY_ALIASES as _UNAVAILABLE_COMPACT_PRIORITY_ALIASES,
)
from .priority_field_policy import _UNAVAILABLE_PRIORITY_ALIASES as _UNAVAILABLE_PRIORITY_ALIASES
from .priority_field_policy import MAX_ROOMING_FIELD_KEY_LENGTH as MAX_ROOMING_FIELD_KEY_LENGTH
from .priority_field_policy import MAX_ROOMING_METADATA_FIELDS as MAX_ROOMING_METADATA_FIELDS
from .priority_field_policy import MAX_ROOMING_PRIORITY_FIELDS as MAX_ROOMING_PRIORITY_FIELDS
from .priority_field_policy import ROOMING_GENDER_RULE as ROOMING_GENDER_RULE
from .priority_field_policy import _clean_value as _clean_value
from .priority_field_policy import _is_unavailable_priority as _is_unavailable_priority
from .priority_field_policy import is_rooming_roster_field as is_rooming_roster_field
from .priority_field_policy import normalize_imported_field_key as normalize_imported_field_key
from .priority_field_values import _recipient_value as _recipient_value
from .priority_field_values import _recipient_values
from .priority_field_values import _submission_field_values as _submission_field_values


@dataclass(frozen=True, slots=True)
class RoomingPriorityContext:
    """Available descriptors and resolved values keyed by passenger."""

    fields: list[dict[str, str]]

    values_by_passenger: dict[uuid.UUID, dict[str, str | None]]


def _passenger_values(
    passengers: list[PassportSubmissionModel],
    value_fields_by_key: dict[str, dict[str, str]],
    *,
    resolve_values: bool,
) -> dict[uuid.UUID, dict[str, str | None]]:
    return (
        {
            passenger.id: _submission_field_values(
                passenger,
                list(value_fields_by_key.values()),
            )
            for passenger in passengers
        }
        if resolve_values
        else {}
    )


def _merge_recipient_values(
    rows: list[SubmissionMatchRow],
    whatsapp_keys: list[str],
    values_by_passenger: dict[uuid.UUID, dict[str, str | None]],
) -> None:
    whatsapp_keys = list(dict.fromkeys(whatsapp_keys))
    for row in rows:
        if row.status not in {"submitted", "multiple_submissions"}:
            continue
        resolved = {
            f"whatsapp:{normalized}": value
            for normalized, value in _recipient_values(row, whatsapp_keys).items()
        }
        for passenger_id in row.submission_ids:
            if passenger_id in values_by_passenger:
                values_by_passenger[passenger_id].update(resolved)


async def build_rooming_priority_context(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    passengers: list[PassportSubmissionModel],
    required_fields: list[dict[str, str]] | None = None,
    requested_keys: list[str] | None = None,
    resolve_values: bool = True,
    lock_inputs: bool = False,
) -> RoomingPriorityContext:
    """Discover the catalog, resolve local values, then merge matched roster data."""
    base_fields = _base_field_definitions(group)
    metadata_fields = _metadata_field_definitions(passengers)
    fields = _deduplicate_labels([*base_fields, *metadata_fields])
    linked_broadcasts: dict[uuid.UUID, str] = {}
    matching_fields_by_broadcast: dict[uuid.UUID, tuple[str, ...] | None] = {}
    recipients: list[WhatsAppBroadcastRecipientModel] = []
    if requested_keys is None or any(key.startswith("whatsapp:") for key in requested_keys):
        linked_broadcasts, matching_fields_by_broadcast = await load_priority_broadcasts(
            session, group, lock_inputs=lock_inputs
        )
        if linked_broadcasts:
            recipients = await load_priority_recipients(
                session, group, linked_broadcasts, lock_inputs=lock_inputs
            )
            fields = _deduplicate_labels(
                [*base_fields, *metadata_fields, *imported_priority_fields(recipients)]
            )
    value_fields_by_key = selected_priority_fields(fields, required_fields, requested_keys)
    values_by_passenger = _passenger_values(
        passengers, value_fields_by_key, resolve_values=resolve_values
    )
    whatsapp_keys = [
        field["key"].removeprefix("whatsapp:")
        for field in value_fields_by_key.values()
        if field["key"].startswith("whatsapp:")
    ]
    if not resolve_values or not whatsapp_keys or not recipients or not passengers:
        return RoomingPriorityContext(fields=fields, values_by_passenger=values_by_passenger)
    comparison_recipients = [
        recipient_comparison_from_model(
            recipient,
            linked_broadcasts,
            matching_fields_by_broadcast,
        )
        for recipient in recipients
    ]
    comparison_submissions = [
        submission_comparison_from_model(passenger) for passenger in passengers
    ]
    rows, _ = compare_group_submissions(comparison_recipients, comparison_submissions)
    _merge_recipient_values(rows, whatsapp_keys, values_by_passenger)
    return RoomingPriorityContext(fields=fields, values_by_passenger=values_by_passenger)
