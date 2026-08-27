"""Export-field, WhatsApp matching, and grouping support for passport routes."""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import (
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientFieldSet,
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportExportHistoryModel,
    PassportRosterResolutionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.export.passport_excel_exporter import (
    PassportExcelExporter,
    passport_age_group,
)
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportKind,
    PassportExportMode,
    PassportExportPersonSnapshot,
    validated_export_people_snapshot,
)

logger = get_logger(__name__)


def _validated_export_history_ids(
    history: PassportExportHistoryModel,
    *,
    field_name: Literal[
        "snapshot_submission_ids",
        "exported_submission_ids",
    ],
) -> set[uuid.UUID]:
    """Validate a persisted export snapshot before using it for a retry."""

    raw_ids = list(getattr(history, field_name) or [])
    parsed_ids: list[uuid.UUID] = []
    for value in raw_ids:
        try:
            parsed_ids.append(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            logger.warning(
                "passport_export_history_invalid_submission_id",
                history_id=str(history.id),
                field_name=field_name,
                value=str(value),
            )
            raise ValueError("The export history entry contains an invalid ID.")
    expected_count = (
        history.total_available_count
        if field_name == "snapshot_submission_ids"
        else history.exported_count
    )
    if len(parsed_ids) != expected_count or len(set(parsed_ids)) != expected_count:
        raise ValueError("The export history entry failed its integrity check.")
    return set(parsed_ids)


def _validated_export_kind(value: str) -> PassportExportKind:
    """Narrow a persisted export kind after validating database integrity."""

    if value not in {"passport_images", "passport_excel"}:
        raise ValueError("The export history entry contains an invalid export kind.")
    return cast(PassportExportKind, value)


def _validated_export_mode(value: str) -> PassportExportMode:
    """Narrow a persisted export mode after validating database integrity."""

    if value not in {"all", "incremental"}:
        raise ValueError("The export history entry contains an invalid export mode.")
    return cast(PassportExportMode, value)


def _export_people_snapshot(
    submissions: list[PassportSubmission],
) -> list[PassportExportPersonSnapshot]:
    people: list[PassportExportPersonSnapshot] = []
    for submission in submissions:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        passport_number = fields.get("passport_number")
        people.append(
            {
                "submission_id": str(submission.id),
                "client_name": submission.client_name,
                "client_phone": submission.client_phone,
                "client_email": submission.client_email,
                "passport_number": (
                    str(passport_number).strip() if passport_number else None
                ),
            }
        )
    return people


def _validated_export_history_people(
    history: PassportExportHistoryModel,
) -> list[PassportExportPersonSnapshot]:
    _validated_export_history_ids(
        history,
        field_name="exported_submission_ids",
    )
    ordered_ids = [
        uuid.UUID(str(value)) for value in (history.exported_submission_ids or [])
    ]
    return validated_export_people_snapshot(
        history.exported_people_snapshot,
        exported_submission_ids=ordered_ids,
    )


def _international_airport_is_enabled(
    group: ClientGroup | ClientGroupModel,
) -> bool:
    """Honor the current option and legacy groups that already stored choices."""

    return group.nearest_international_airport_enabled or bool(group.departure_cities)


def _group_export_details(
    group: ClientGroup | ClientGroupModel,
) -> dict[str, Any]:
    return {
        "name": group.name,
        "destination": group.destination,
        "travel_date": group.travel_date.isoformat() if group.travel_date else None,
        "return_date": group.return_date.isoformat() if group.return_date else None,
        "package_name": group.package_name,
        "nearest_international_airport_enabled": (_international_airport_is_enabled(group)),
        "ask_nearest_domestic_airport": group.ask_nearest_domestic_airport,
        "base_city_enabled": group.base_city_enabled,
        "staff_code_enabled": group.staff_code_enabled,
        "agent_employee_code_enabled": group.agent_employee_code_enabled,
        "meal_preference_enabled": group.meal_preference_enabled,
        "relation_with_qualifier_enabled": (group.relation_with_qualifier_enabled),
        "designation_enabled": group.designation_enabled,
        "agency_dealership_name_enabled": (group.agency_dealership_name_enabled),
        "custom_questions": list(group.custom_questions or []),
        "custom_details": list(group.custom_details or []),
    }


async def _export_group_details(
    session: AsyncSession,
    group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, Any]]:
    if not group_ids:
        return {}
    result = await session.execute(
        select(ClientGroupModel).where(ClientGroupModel.id.in_(set(group_ids)))
    )
    return {group.id: _group_export_details(group) for group in result.scalars().all()}


def _normalized_imported_field_key(value: str) -> str:
    return "_".join(
        part
        for part in "".join(
            character.casefold() if character.isalnum() else " " for character in value
        ).split()
        if part
    )


def _imported_zone_name(fields: Mapping[str, object]) -> str | None:
    for key, value in fields.items():
        if _normalized_imported_field_key(str(key)) not in {
            "zone_name",
            "zonename",
            "zone",
        }:
            continue
        normalized = " ".join(str(value or "").strip().split())
        if normalized and normalized.casefold() not in {"null", "none", "n/a", "na"}:
            return normalized
    return None


async def _export_whatsapp_match_rows(
    session: AsyncSession,
    submissions: list[PassportSubmission],
    *,
    groups: list[ClientGroup] | None = None,
) -> dict[uuid.UUID, list[SubmissionMatchRow]]:
    """Build one production-grade recipient/submission comparison per group."""
    submissions_by_group: dict[uuid.UUID, list[PassportSubmission]] = {
        group.id: [] for group in (groups or [])
    }
    agency_ids: set[uuid.UUID] = set()
    for group in groups or []:
        if group.agency_id:
            agency_ids.add(group.agency_id)
    for submission in submissions:
        submissions_by_group.setdefault(submission.group_id, []).append(submission)
        if submission.agency_id:
            agency_ids.add(submission.agency_id)
    if not submissions_by_group or not agency_ids:
        return {}

    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id.in_(set(submissions_by_group)),
            ClientGroupWhatsAppBroadcastLinkModel.agency_id.in_(agency_ids),
            WhatsAppBroadcastGroupModel.agency_id.in_(agency_ids),
        )
    )
    linked_by_group: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
    for group_id, broadcast_id, broadcast_name in linked_result.all():
        linked_by_group.setdefault(group_id, {})[broadcast_id] = broadcast_name
    broadcast_ids = {
        broadcast_id for broadcasts in linked_by_group.values() for broadcast_id in broadcasts
    }
    if not broadcast_ids:
        return {}

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(broadcast_ids),
            WhatsAppBroadcastRecipientModel.agency_id.in_(agency_ids),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    )
    recipients_by_broadcast: dict[
        uuid.UUID,
        list[WhatsAppBroadcastRecipientModel],
    ] = {}
    for recipient in recipient_result.scalars().all():
        recipients_by_broadcast.setdefault(
            recipient.broadcast_group_id,
            [],
        ).append(recipient)

    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]] = {}
    for group_id, group_submissions in submissions_by_group.items():
        linked_broadcasts = linked_by_group.get(group_id, {})
        if not linked_broadcasts:
            continue
        comparison_recipients = [
            RecipientForComparison(
                id=recipient.id,
                broadcast_id=broadcast_id,
                broadcast_name=broadcast_name,
                name=recipient.name,
                phone=recipient.normalized_phone_number,
                updated_at=recipient.created_at,
                imported_fields=dict(recipient.imported_fields or {}),
            )
            for broadcast_id, broadcast_name in linked_broadcasts.items()
            for recipient in recipients_by_broadcast.get(broadcast_id, [])
        ]
        comparison_submissions = [
            SubmissionForComparison(
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
            )
            for submission in group_submissions
        ]
        rows, _ = compare_group_submissions(
            comparison_recipients,
            comparison_submissions,
        )
        rows_by_group[group_id] = rows
    return rows_by_group


def _stored_resolution_uuid_list(values: list[str] | None) -> list[uuid.UUID]:
    parsed: list[uuid.UUID] = []
    for value in values or []:
        try:
            parsed.append(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return parsed


async def _whatsapp_tracking_export_rows(
    session: AsyncSession,
    *,
    group: ClientGroup,
    submissions: list[PassportSubmission],
) -> tuple[dict[uuid.UUID, str], list[SubmissionMatchRow]]:
    """Build the same complete roster view used by WhatsApp tracking."""

    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
            WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
        )
    )
    linked_broadcasts = {
        broadcast_id: broadcast_name for broadcast_id, broadcast_name in linked_result.all()
    }

    resolution_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    active_resolutions = list(resolution_result.scalars().all())
    suppressed_recipient_ids = {
        recipient_id
        for resolution in active_resolutions
        for recipient_id in _stored_resolution_uuid_list(resolution.suppressed_recipient_ids)
    }
    excluded_submission_ids = {
        submission_id
        for resolution in active_resolutions
        for submission_id in (
            [resolution.submission_id]
            + _stored_resolution_uuid_list(resolution.excluded_submission_ids)
        )
    }

    recipient_models: list[WhatsAppBroadcastRecipientModel] = []
    if linked_broadcasts:
        recipient_visibility = (
            or_(
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                WhatsAppBroadcastRecipientModel.id.in_(suppressed_recipient_ids),
            )
            if suppressed_recipient_ids
            else WhatsAppBroadcastRecipientModel.removed_at.is_(None)
        )
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked_broadcasts)),
                recipient_visibility,
            )
        )
        recipient_models = list(recipient_result.scalars().all())
    recipients_by_id = {recipient.id: recipient for recipient in recipient_models}
    comparison_recipients = [
        RecipientForComparison(
            id=recipient.id,
            broadcast_id=recipient.broadcast_group_id,
            broadcast_name=linked_broadcasts[recipient.broadcast_group_id],
            name=recipient.name,
            phone=recipient.normalized_phone_number,
            updated_at=recipient.created_at,
            imported_fields=dict(recipient.imported_fields or {}),
        )
        for recipient in recipient_models
        if recipient.removed_at is None and recipient.id not in suppressed_recipient_ids
    ]
    submissions_by_id = {submission.id: submission for submission in submissions}
    comparison_submissions = [
        SubmissionForComparison(
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
        )
        for submission in submissions
        if submission.id not in excluded_submission_ids
    ]
    rows, _counts = compare_group_submissions(
        comparison_recipients,
        comparison_submissions,
    )

    for resolution in active_resolutions:
        submission = submissions_by_id.get(resolution.submission_id)
        if submission is None:
            continue
        if resolution.resolution_type == "replacement":
            suppressed = [
                recipients_by_id[recipient_id]
                for recipient_id in _stored_resolution_uuid_list(
                    resolution.suppressed_recipient_ids
                )
                if recipient_id in recipients_by_id
            ]
            broadcast_pairs = list(
                dict.fromkeys(
                    (
                        recipient.broadcast_group_id,
                        linked_broadcasts.get(
                            recipient.broadcast_group_id,
                            "Linked broadcast",
                        ),
                    )
                    for recipient in suppressed
                )
            )
            selected_recipient_id = resolution.broadcast_recipient_id
            selected_recipient = (
                recipients_by_id.get(selected_recipient_id)
                if selected_recipient_id is not None
                else None
            )
            rows.append(
                SubmissionMatchRow(
                    status="replacement",
                    match_basis="manual_replacement",
                    normalized_phone=(
                        selected_recipient.normalized_phone_number if selected_recipient else None
                    ),
                    recipient_ids=tuple(recipient.id for recipient in suppressed),
                    submission_ids=(submission.id,),
                    broadcast_ids=tuple(item[0] for item in broadcast_pairs),
                    broadcast_names=tuple(item[1] for item in broadcast_pairs),
                    recipient_names=tuple(
                        recipient.name or "Unnamed recipient" for recipient in suppressed
                    ),
                    submission_names=(submission.client_name,),
                    updated_at=max(submission.updated_at, resolution.created_at),
                    confidence="high",
                    recipient_fields=tuple(
                        RecipientFieldSet(
                            recipient_id=recipient.id,
                            fields=dict(recipient.imported_fields or {}),
                        )
                        for recipient in suppressed
                    ),
                    resolution_id=resolution.id,
                )
            )
        else:
            rows.append(
                SubmissionMatchRow(
                    status="rejected_upload",
                    match_basis="manual_rejection",
                    normalized_phone=normalize_whatsapp_phone(submission.client_phone or ""),
                    recipient_ids=(),
                    submission_ids=(submission.id,),
                    broadcast_ids=(),
                    broadcast_names=(),
                    recipient_names=(),
                    submission_names=(submission.client_name,),
                    updated_at=max(submission.updated_at, resolution.created_at),
                    confidence="high",
                    resolution_id=resolution.id,
                )
            )
    return linked_broadcasts, rows


def _select_whatsapp_tracking_export_payload(
    submissions: list[PassportSubmission],
    rows: list[SubmissionMatchRow],
    *,
    tracking_status: str,
    broadcast_id: uuid.UUID | None,
) -> tuple[list[PassportSubmission], list[SubmissionMatchRow]]:
    selected_rows = [
        row
        for row in rows
        if (
            (tracking_status == "all" or row.status == tracking_status)
            and (broadcast_id is None or broadcast_id in row.broadcast_ids)
        )
    ]
    selected_submission_ids = {
        submission_id
        for row in selected_rows
        for submission_id in (
            row.candidate_submission_ids if row.status == "needs_review" else row.submission_ids
        )
    }
    return (
        [submission for submission in submissions if submission.id in selected_submission_ids],
        selected_rows,
    )


def _export_zone_names_from_match_rows(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
) -> dict[uuid.UUID, str]:
    resolved: dict[uuid.UUID, str] = {}
    submissions_by_group: dict[uuid.UUID, list[PassportSubmission]] = {}
    for submission in submissions:
        submissions_by_group.setdefault(submission.group_id, []).append(submission)

    for group_id, group_submissions in submissions_by_group.items():
        rows = rows_by_group.get(group_id, [])
        submissions_by_id = {submission.id: submission for submission in group_submissions}
        for row in rows:
            if row.status not in {
                "submitted",
                "multiple_submissions",
                "replacement",
            }:
                continue
            zones_by_key: dict[str, str] = {}
            for field_set in row.recipient_fields:
                zone_name = _imported_zone_name(field_set.fields)
                if zone_name:
                    zones_by_key.setdefault(zone_name.casefold(), zone_name)
            if not zones_by_key:
                continue
            for submission_id in row.submission_ids:
                if len(zones_by_key) == 1:
                    resolved[submission_id] = next(iter(zones_by_key.values()))
                    continue
                matched_submission = submissions_by_id.get(submission_id)
                stored_zone = _imported_zone_name(
                    matched_submission.staff_metadata or {}
                    if matched_submission is not None
                    else {}
                )
                if stored_zone and stored_zone.casefold() in zones_by_key:
                    resolved[submission_id] = zones_by_key[stored_zone.casefold()]
    return resolved


async def _export_zone_names(
    session: AsyncSession,
    submissions: list[PassportSubmission],
) -> dict[uuid.UUID, str]:
    """Resolve exact imported WhatsApp zones using the production matcher."""

    rows_by_group = await _export_whatsapp_match_rows(session, submissions)
    return _export_zone_names_from_match_rows(submissions, rows_by_group)


def _recipient_export_value(
    row: SubmissionMatchRow,
    *keys: str,
) -> str | None:
    values_by_key: dict[str, str] = {}
    accepted_keys = {_normalized_imported_field_key(key) for key in keys}
    for field_set in sorted(row.recipient_fields, key=lambda item: str(item.recipient_id)):
        for raw_key, raw_value in field_set.fields.items():
            if _normalized_imported_field_key(str(raw_key)) not in accepted_keys:
                continue
            value = " ".join(str(raw_value or "").strip().split())
            if not value or value.casefold() in {"null", "none", "n/a", "na"}:
                continue
            values_by_key.setdefault(value.casefold(), value)
    if len(values_by_key) == 1:
        return next(iter(values_by_key.values()))
    # Conflicting imported identities must not be silently assigned to a
    # random zone/person. Leave the ambiguous field empty for staff review.
    return None


def _recipient_old_given_name(row: SubmissionMatchRow) -> str | None:
    """Return the best unambiguous WhatsApp name for one matched recipient."""

    given_names = _recipient_export_value(
        row,
        "given_names",
        "given_name",
        "first_name",
    )
    if given_names:
        return given_names

    recipient_names_by_key = {
        normalized.casefold(): normalized
        for name in row.recipient_names
        if (normalized := " ".join(str(name or "").strip().split()))
    }
    if len(recipient_names_by_key) == 1:
        return next(iter(recipient_names_by_key.values()))

    imported_name = _recipient_export_value(
        row,
        "name",
        "full_name",
        "client_name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "employee_name",
    )
    if imported_name:
        return imported_name

    return _recipient_export_value(
        row,
        "surname",
        "last_name",
        "family_name",
    )


_WHATSAPP_EMAIL_IMPORTED_KEYS = (
    "email",
    "email_id",
    "email_address",
    "e_mail",
    "mail",
)
_WHATSAPP_PHONE_IMPORTED_KEYS = (
    "phone_number",
    "phone",
    "mobile",
    "mobile_number",
    "whatsapp",
    "whatsapp_number",
    "contact",
    "contact_number",
)


def _export_whatsapp_contacts(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
) -> dict[uuid.UUID, dict[str, str | None]]:
    """Resolve matched broadcast contacts without mixing them with upload data."""

    candidates: dict[uuid.UUID, dict[str, dict[str, str]]] = {
        submission.id: {"email": {}, "phone": {}} for submission in submissions
    }

    def add_candidate(
        submission_id: uuid.UUID,
        field: Literal["email", "phone"],
        value: str | None,
    ) -> None:
        normalized = " ".join(str(value or "").strip().split())
        if (
            not normalized
            or normalized.casefold() in {"null", "none", "n/a", "na"}
            or submission_id not in candidates
        ):
            return
        candidates[submission_id][field].setdefault(normalized.casefold(), normalized)

    for rows in rows_by_group.values():
        for row in rows:
            if row.status not in {
                "submitted",
                "multiple_submissions",
                "replacement",
            }:
                continue
            email = _recipient_export_value(
                row,
                *_WHATSAPP_EMAIL_IMPORTED_KEYS,
            )
            phone = row.normalized_phone or _recipient_export_value(
                row,
                *_WHATSAPP_PHONE_IMPORTED_KEYS,
            )
            for submission_id in row.submission_ids:
                add_candidate(submission_id, "email", email)
                add_candidate(submission_id, "phone", phone)

    contacts: dict[uuid.UUID, dict[str, str | None]] = {}
    for submission_id, fields in candidates.items():
        contacts[submission_id] = {
            field: next(iter(values.values())) if len(values) == 1 else None
            for field, values in fields.items()
        }
    return contacts


def _pending_recipient_export_rows(
    *,
    group: ClientGroup,
    rows: list[SubmissionMatchRow],
    excluded_recipient_ids: frozenset[uuid.UUID] = frozenset(),
    include_name_history: bool = False,
) -> list[dict[str, Any]]:
    details = _group_export_details(group)
    pending_rows: list[dict[str, Any]] = []
    for row in rows:
        if (
            not row.recipient_ids
            or row.status not in {"not_submitted", "needs_review"}
            or any(recipient_id in excluded_recipient_ids for recipient_id in row.recipient_ids)
        ):
            continue
        given_names = _recipient_export_value(
            row,
            "given_names",
            "given_name",
            "first_name",
        )
        surname = _recipient_export_value(
            row,
            "surname",
            "last_name",
            "family_name",
        )
        imported_name = _recipient_export_value(
            row,
            "name",
            "full_name",
            "client_name",
            "passenger_name",
            "recipient_name",
            "staff_name",
            "employee_name",
        )
        recipient_names_by_key = {
            normalized.casefold(): normalized
            for name in row.recipient_names
            if (normalized := " ".join(str(name or "").strip().split()))
        }
        unambiguous_recipient_name = (
            next(iter(recipient_names_by_key.values()))
            if len(recipient_names_by_key) == 1
            else None
        )
        client_name = (
            unambiguous_recipient_name
            or imported_name
            or " ".join(part for part in (given_names, surname) if part)
            or row.normalized_phone
            or "Pending recipient"
        )
        date_of_birth = _recipient_export_value(
            row,
            "date_of_birth",
            "dob",
            "birth_date",
        )
        pending_rows.append(
            {
                "Group": details.get("name") or group.name,
                "Destination": details.get("destination"),
                "Travel/Departure Date": details.get("travel_date"),
                "Return Date": details.get("return_date"),
                "Zone Name": _recipient_export_value(
                    row,
                    "zone_name",
                    "zonename",
                    "zone",
                ),
                "Agency/Dealership Name": _recipient_export_value(
                    row,
                    "agency_dealership_name",
                    "agency_name",
                    "dealership_name",
                ),
                "Designation": _recipient_export_value(row, "designation"),
                "Age Group": passport_age_group(
                    date_of_birth,
                    details.get("travel_date"),
                ),
                "WhatsApp Email": _recipient_export_value(
                    row,
                    *_WHATSAPP_EMAIL_IMPORTED_KEYS,
                ),
                "WhatsApp Phone": (
                    row.normalized_phone
                    or _recipient_export_value(
                        row,
                        *_WHATSAPP_PHONE_IMPORTED_KEYS,
                    )
                ),
                "International Airport": _recipient_export_value(
                    row,
                    "nearest_international_airport",
                    "international_airport",
                    "departure_city",
                ),
                "Domestic Airport": _recipient_export_value(
                    row,
                    "nearest_domestic_airport",
                    "domestic_airport",
                ),
                "Base City": _recipient_export_value(row, "base_city"),
                "Staff Code": _recipient_export_value(
                    row,
                    "staff_code",
                    "staffcode",
                    "employee_code",
                    "staff_id",
                ),
                "Agent/Employee Code": _recipient_export_value(
                    row,
                    "agent_employee_code",
                    "agent_code",
                    "employee_code",
                ),
                "Meal Preference": _recipient_export_value(
                    row,
                    "meal_preference",
                    "meal",
                    "food_preference",
                ),
                "Relation with Qualifier": _recipient_export_value(
                    row,
                    "relation_with_qualifier",
                    "qualifier_relation",
                    "relation",
                ),
                "SURNAME": surname.upper() if surname else None,
                "GIVEN NAME": (given_names.upper() if given_names else client_name.upper()),
                "GENDER": (
                    value.upper()
                    if (value := _recipient_export_value(row, "sex", "gender"))
                    else None
                ),
                "Passport Number": _recipient_export_value(
                    row,
                    "passport_number",
                    "passport_no",
                    "passport",
                ),
                "DOB": date_of_birth,
                "DOI": _recipient_export_value(
                    row,
                    "date_of_issue",
                    "issue_date",
                ),
                "DOE": _recipient_export_value(
                    row,
                    "date_of_expiry",
                    "expiry_date",
                    "expiration_date",
                ),
                "Nationality": _recipient_export_value(row, "nationality"),
                "Place of Issue": _recipient_export_value(
                    row,
                    "place_of_issue",
                    "issue_place",
                ),
            }
        )
        if include_name_history:
            pending_rows[-1].update(
                {
                    "Old Given Name": (
                        old_given_name.upper()
                        if (old_given_name := _recipient_old_given_name(row))
                        else None
                    ),
                    "New Surname": None,
                    "New Given Name": None,
                }
            )
    return pending_rows


_WHATSAPP_SOURCE_METADATA_KEYS = {
    "row_number",
    "sheet_name",
    "source_file",
    "source_order",
    "source_row",
    "source_sheet",
}
_FIXED_IMPORTED_EXPORT_KEYS = {
    "name",
    "full_name",
    "client_name",
    "passenger_name",
    "recipient_name",
    "staff_name",
    "employee_name",
    "given_names",
    "given_name",
    "first_name",
    "surname",
    "last_name",
    "family_name",
    *_WHATSAPP_EMAIL_IMPORTED_KEYS,
    *_WHATSAPP_PHONE_IMPORTED_KEYS,
    "passport_number",
    "passport_no",
    "passport",
    "nationality",
    "place_of_issue",
    "issue_place",
    "date_of_birth",
    "dob",
    "birth_date",
    "date_of_issue",
    "issue_date",
    "date_of_expiry",
    "expiry_date",
    "expiration_date",
    "sex",
    "gender",
    "nearest_international_airport",
    "international_airport",
    "departure_city",
    "nearest_domestic_airport",
    "domestic_airport",
    "base_city",
    "staff_code",
    "staffcode",
    "staff_id",
    "agent_employee_code",
    "agent_code",
    "employee_code",
    "meal_preference",
    "meal",
    "food_preference",
    "relation_with_qualifier",
    "qualifier_relation",
    "relation",
    "designation",
    "agency_dealership_name",
    "agency_name",
    "dealership_name",
    *_WHATSAPP_SOURCE_METADATA_KEYS,
}
_ZONE_IMPORTED_KEYS = {"zone_name", "zonename", "zone"}
_AGENCY_MATCH_SIMILARITY_THRESHOLD = 0.90


def _export_field_catalog(
    group: ClientGroup,
    rows: list[SubmissionMatchRow],
    submissions: list[PassportSubmission] | None = None,
) -> list[dict[str, str | bool]]:
    """List selectable supplemental columns with stable keys and labels."""

    used_labels = {str(header).casefold() for header in PassportExcelExporter.HEADERS}

    def unique_label(label: str, source_label: str) -> str:
        candidate = label[:120]
        suffix_index = 1
        while candidate.casefold() in used_labels:
            suffix = (
                f" ({source_label})" if suffix_index == 1 else f" ({source_label} {suffix_index})"
            )
            candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
            suffix_index += 1
        used_labels.add(candidate.casefold())
        return candidate

    imported_labels: dict[str, str] = {}
    for row in rows:
        for field_set in row.recipient_fields:
            for raw_key in field_set.fields:
                normalized = _normalized_imported_field_key(str(raw_key))
                if not normalized or normalized in _FIXED_IMPORTED_EXPORT_KEYS:
                    continue
                if normalized in _ZONE_IMPORTED_KEYS:
                    imported_labels["zone_name"] = "Zone Name"
                    continue
                imported_labels.setdefault(
                    normalized,
                    " ".join(str(raw_key).strip().split())[:120],
                )

    fields: list[dict[str, str | bool]] = []
    for normalized, label in imported_labels.items():
        key = "zone_name" if normalized == "zone_name" else f"whatsapp:{normalized}"
        fields.append(
            {
                "key": key,
                "label": ("Zone Name" if key == "zone_name" else unique_label(label, "WhatsApp")),
                "source": "whatsapp",
                "selected_by_default": key == "zone_name",
            }
        )
    return sorted(
        fields,
        key=lambda field: (
            field["key"] != "zone_name",
            str(field["label"]).casefold(),
            str(field["key"]),
        ),
    )


def _export_agency_match_field_catalog(
    group: ClientGroup,
    rows: list[SubmissionMatchRow],
) -> list[dict[str, str | bool]]:
    """List every user-imported WhatsApp field that can identify an agency."""

    if not group.agency_dealership_name_enabled:
        return []

    imported_labels: dict[str, str] = {}
    for row in rows:
        for field_set in row.recipient_fields:
            for raw_key in field_set.fields:
                normalized = _normalized_imported_field_key(str(raw_key))
                if not normalized or normalized in _WHATSAPP_SOURCE_METADATA_KEYS:
                    continue
                imported_labels.setdefault(
                    normalized,
                    " ".join(str(raw_key).strip().split())[:120],
                )

    return [
        {
            "key": f"whatsapp:{normalized}",
            "label": label,
            "source": "whatsapp",
            "selected_by_default": False,
        }
        for normalized, label in sorted(
            imported_labels.items(),
            key=lambda item: (item[1].casefold(), item[0]),
        )
    ]


def _agency_match_export_field(
    match_field: dict[str, str | bool],
) -> dict[str, str | bool]:
    """Expose the selected match value automatically without duplicating its picker."""

    label = " ".join(str(match_field["label"]).strip().split()) or "Match Value"
    old_label = label if label.casefold().startswith("old ") else f"Old {label}"
    return {
        "key": str(match_field["key"]),
        "label": old_label[:120],
        "source": "whatsapp",
        "selected_by_default": True,
    }


@dataclass(frozen=True)
class _AgencyExportMatches:
    rows_by_submission: dict[uuid.UUID, SubmissionMatchRow]
    matched_recipient_ids: frozenset[uuid.UUID]


def _normalized_agency_match_value(value: Any) -> str:
    compatible = unicodedata.normalize("NFKC", str(value or "")).casefold()
    compatible = compatible.replace("&", " and ")
    normalized = "".join(character if character.isalnum() else " " for character in compatible)
    return " ".join(normalized.split())


def _agency_match_similarity(left: Any, right: Any) -> float:
    normalized_left = _normalized_agency_match_value(left)
    normalized_right = _normalized_agency_match_value(right)
    if not normalized_left or not normalized_right:
        return 0.0
    compact_left = normalized_left.replace(" ", "")
    compact_right = normalized_right.replace(" ", "")
    if compact_left == compact_right:
        return 1.0
    if min(len(compact_left), len(compact_right)) < 4:
        return 0.0
    maximum_possible = (
        2 * min(len(compact_left), len(compact_right)) / (len(compact_left) + len(compact_right))
    )
    if maximum_possible < _AGENCY_MATCH_SIMILARITY_THRESHOLD:
        return 0.0
    return SequenceMatcher(
        None,
        compact_left,
        compact_right,
        autojunk=False,
    ).ratio()


def _submission_agency_dealership_name(
    submission: PassportSubmission,
) -> str | None:
    fields = dict(submission.extracted_fields or {})
    fields.update(submission.confirmed_fields or {})
    value = fields.get("agency_dealership_name") or (submission.staff_metadata or {}).get(
        "agency_dealership_name"
    )
    normalized = " ".join(str(value or "").strip().split())
    return normalized or None


def _export_agency_matches(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
    agency_match_field: str,
) -> _AgencyExportMatches:
    """Resolve one unambiguous WhatsApp row per submitted agency value."""

    normalized_field = agency_match_field.removeprefix("whatsapp:")
    if not normalized_field or normalized_field == agency_match_field:
        return _AgencyExportMatches({}, frozenset())

    candidates_by_group: dict[
        uuid.UUID,
        list[tuple[str, SubmissionMatchRow]],
    ] = {}
    exact_rows_by_group: dict[
        uuid.UUID,
        dict[str, list[SubmissionMatchRow]],
    ] = {}
    for group_id, rows in rows_by_group.items():
        for row in rows:
            if not row.recipient_ids:
                continue
            imported_agency = _recipient_export_value(row, normalized_field)
            normalized_agency = _normalized_agency_match_value(imported_agency)
            if not normalized_agency:
                continue
            candidates_by_group.setdefault(group_id, []).append((normalized_agency, row))
            exact_rows_by_group.setdefault(group_id, {}).setdefault(
                normalized_agency.replace(" ", ""),
                [],
            ).append(row)

    rows_by_submission: dict[uuid.UUID, SubmissionMatchRow] = {}
    matched_recipient_ids: set[uuid.UUID] = set()
    for submission in submissions:
        agency_name = _submission_agency_dealership_name(submission)
        if not agency_name:
            continue

        normalized_agency = _normalized_agency_match_value(agency_name)
        exact_rows = exact_rows_by_group.get(submission.group_id, {}).get(
            normalized_agency.replace(" ", ""),
            [],
        )
        if exact_rows:
            best_rows = exact_rows
        else:
            scored_rows = [
                (score, row)
                for candidate, row in candidates_by_group.get(
                    submission.group_id,
                    [],
                )
                if (
                    score := _agency_match_similarity(
                        normalized_agency,
                        candidate,
                    )
                )
                >= _AGENCY_MATCH_SIMILARITY_THRESHOLD
            ]
            if not scored_rows:
                continue
            best_score = max(score for score, _ in scored_rows)
            best_rows = [row for score, row in scored_rows if abs(score - best_score) < 1e-12]
        if len(best_rows) != 1:
            # Duplicate agency values can refer to different people. Never
            # choose one arbitrarily and copy the wrong roster details.
            continue
        matched_row = best_rows[0]
        rows_by_submission[submission.id] = matched_row
        matched_recipient_ids.update(matched_row.recipient_ids)

    return _AgencyExportMatches(
        rows_by_submission=rows_by_submission,
        matched_recipient_ids=frozenset(matched_recipient_ids),
    )


def _export_effective_whatsapp_matches(
    agency_matches: _AgencyExportMatches,
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
) -> _AgencyExportMatches:
    """Prefer agency matches, then use each submission's existing WhatsApp match."""

    fallback_rows: dict[uuid.UUID, SubmissionMatchRow] = {}
    ambiguous_submission_ids: set[uuid.UUID] = set()
    for rows in rows_by_group.values():
        for row in rows:
            if row.status not in {
                "submitted",
                "multiple_submissions",
                "replacement",
            }:
                continue
            for submission_id in row.submission_ids:
                if submission_id in ambiguous_submission_ids:
                    continue
                existing = fallback_rows.get(submission_id)
                if existing is None:
                    fallback_rows[submission_id] = row
                elif existing is not row:
                    fallback_rows.pop(submission_id, None)
                    ambiguous_submission_ids.add(submission_id)

    rows_by_submission = {
        **fallback_rows,
        **agency_matches.rows_by_submission,
    }
    matched_recipient_ids = set(agency_matches.matched_recipient_ids)
    for row in rows_by_submission.values():
        matched_recipient_ids.update(row.recipient_ids)
    return _AgencyExportMatches(
        rows_by_submission=rows_by_submission,
        matched_recipient_ids=frozenset(matched_recipient_ids),
    )


def _apply_agency_export_matches(
    matches: _AgencyExportMatches,
    selected_fields: list[dict[str, str | bool]],
    agency_match_field: str,
    *,
    additional_values: dict[uuid.UUID, dict[str, str | None]],
    whatsapp_contacts: dict[uuid.UUID, dict[str, str | None]],
    zone_names: dict[uuid.UUID, str],
) -> dict[uuid.UUID, dict[str, str | None]]:
    """Fill WhatsApp-derived export data from each submission's effective row."""

    previous_names: dict[uuid.UUID, dict[str, str | None]] = {}
    normalized_match_field = agency_match_field.removeprefix("whatsapp:")
    for submission_id, row in matches.rows_by_submission.items():
        row_values = additional_values.setdefault(submission_id, {})
        row_values[agency_match_field] = _recipient_export_value(
            row,
            normalized_match_field,
        )
        for field in selected_fields:
            key = str(field["key"])
            if key == agency_match_field:
                continue
            if key.startswith("whatsapp:"):
                row_values[key] = _recipient_export_value(
                    row,
                    key.removeprefix("whatsapp:"),
                )
            elif key == "zone_name":
                zone_names.pop(submission_id, None)
                zone_name = _recipient_export_value(
                    row,
                    "zone_name",
                    "zonename",
                    "zone",
                )
                if zone_name:
                    zone_names[submission_id] = zone_name

        whatsapp_contacts[submission_id] = {
            "email": _recipient_export_value(
                row,
                *_WHATSAPP_EMAIL_IMPORTED_KEYS,
            ),
            "phone": (
                row.normalized_phone
                or _recipient_export_value(
                    row,
                    *_WHATSAPP_PHONE_IMPORTED_KEYS,
                )
            ),
        }
        previous_names[submission_id] = {
            "given_names": _recipient_old_given_name(row),
        }
    return previous_names


def _merge_export_field_catalogs(
    catalogs: list[list[dict[str, str | bool]]],
) -> list[dict[str, str | bool]]:
    """Place fields shared by every group before group-specific fields."""

    if not catalogs:
        return []

    keyed_catalogs = [{str(field["key"]): field for field in catalog} for catalog in catalogs]
    common_keys = set(keyed_catalogs[0])
    for keyed_catalog in keyed_catalogs[1:]:
        common_keys.intersection_update(keyed_catalog)

    selected_by_default = {
        key: any(
            bool(keyed_catalog.get(key, {}).get("selected_by_default", False))
            for keyed_catalog in keyed_catalogs
        )
        for key in {key for keyed_catalog in keyed_catalogs for key in keyed_catalog}
    }
    merged: list[dict[str, str | bool]] = []
    seen: set[str] = set()
    used_labels = {str(header).casefold() for header in PassportExcelExporter.HEADERS}

    def append_field(field: dict[str, str | bool]) -> None:
        key = str(field["key"])
        if key in seen:
            return
        label = " ".join(str(field["label"]).strip().split())[:120]
        candidate = label
        suffix_index = 1
        while candidate.casefold() in used_labels:
            suffix = " (WhatsApp)" if suffix_index == 1 else f" (WhatsApp {suffix_index})"
            candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
            suffix_index += 1
        seen.add(key)
        used_labels.add(candidate.casefold())
        merged.append(
            {
                **field,
                "label": candidate,
                "selected_by_default": selected_by_default.get(key, False),
            }
        )

    # Zone has an explicit workbook position immediately after Return Date,
    # even when it exists in only one of the selected broadcasts.
    for keyed_catalog in keyed_catalogs:
        zone_field = keyed_catalog.get("zone_name")
        if zone_field is not None:
            append_field(zone_field)
            break
    for field in catalogs[0]:
        if str(field["key"]) in common_keys and str(field["key"]) != "zone_name":
            append_field(field)
    for catalog in catalogs:
        for field in catalog:
            if str(field["key"]) not in common_keys and str(field["key"]) != "zone_name":
                append_field(field)
    return merged


def _combined_export_field_catalog(
    groups: list[ClientGroup],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
    submissions: list[PassportSubmission],
) -> list[dict[str, str | bool]]:
    submissions_by_group: dict[uuid.UUID, list[PassportSubmission]] = {}
    for submission in submissions:
        submissions_by_group.setdefault(submission.group_id, []).append(submission)
    return _merge_export_field_catalogs(
        [
            _export_field_catalog(
                group,
                rows_by_group.get(group.id, []),
                submissions_by_group.get(group.id, []),
            )
            for group in groups
        ]
    )


def _export_additional_values(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
    selected_fields: list[dict[str, str | bool]],
) -> dict[uuid.UUID, dict[str, str | None]]:
    values: dict[uuid.UUID, dict[str, str | None]] = {
        submission.id: {} for submission in submissions
    }
    selected_whatsapp = [
        field for field in selected_fields if str(field["key"]).startswith("whatsapp:")
    ]
    for rows in rows_by_group.values():
        for row in rows:
            if row.status not in {
                "submitted",
                "multiple_submissions",
                "replacement",
            }:
                continue
            for submission_id in row.submission_ids:
                if submission_id not in values:
                    continue
                for field in selected_whatsapp:
                    normalized = str(field["key"]).removeprefix("whatsapp:")
                    values[submission_id][str(field["key"])] = _recipient_export_value(
                        row,
                        normalized,
                    )

    return values


def _apply_pending_export_fields(
    pending_rows: list[dict[str, Any]],
    match_rows: list[SubmissionMatchRow],
    selected_fields: list[dict[str, str | bool]],
    *,
    excluded_recipient_ids: frozenset[uuid.UUID] = frozenset(),
) -> None:
    source_rows = [
        row
        for row in match_rows
        if (
            row.recipient_ids
            and row.status in {"not_submitted", "needs_review"}
            and not any(
                recipient_id in excluded_recipient_ids for recipient_id in row.recipient_ids
            )
        )
    ]
    for exported_row, source_row in zip(pending_rows, source_rows, strict=True):
        for field in selected_fields:
            key = str(field["key"])
            if key == "zone_name":
                exported_row[str(field["label"])] = _recipient_export_value(
                    source_row,
                    "zone_name",
                    "zonename",
                    "zone",
                )
            elif key.startswith("whatsapp:"):
                exported_row[str(field["label"])] = _recipient_export_value(
                    source_row,
                    key.removeprefix("whatsapp:"),
                )
