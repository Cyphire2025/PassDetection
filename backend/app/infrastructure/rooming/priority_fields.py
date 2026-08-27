"""Discover and resolve safe room-allocation priority fields."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)

MAX_ROOMING_PRIORITY_FIELDS = 6
MAX_ROOMING_METADATA_FIELDS = 256
MAX_ROOMING_FIELD_KEY_LENGTH = 180
ROOMING_GENDER_RULE = (
    "Male passengers are paired only with male passengers; "
    "female passengers only with female passengers."
)

_UNAVAILABLE_PRIORITY_ALIASES = frozenset(
    {
        # Required fixed output columns.
        "staff_code",
        "staffcode",
        "staff_id",
        "employee_id",
        "emp_id",
        "national_id",
        "government_id",
        "govt_id",
        "tax_id",
        "customer_id",
        "client_id",
        "voter_id",
        "ssn",
        "tin",
        "gstin",
        "agent_employee_code",
        "agent_employee_type",
        "agent_code",
        "employee_code",
        "age",
        "age_group",
        "given_names",
        "given_name",
        "first_name",
        "surname",
        "last_name",
        "family_name",
        "name",
        "full_name",
        "client_name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "employee_name",
        "sex",
        "gender",
        "passport_number",
        "passport_num",
        "passport_no",
        "passport",
        "passportnum",
        "date_of_birth",
        "dob",
        "birth_date",
        "date_of_issue",
        "dateofissue",
        "issue_date",
        "doi",
        "date_of_expiry",
        "dateofexpiry",
        "expiry_date",
        "expiration_date",
        "doe",
        "place_of_issue",
        "placeofissue",
        "issue_place",
        "room_number",
        "room_type",
        "vip",
        # Import provenance is not a traveller attribute.
        "source_file",
        "source_sheet",
        "sheet_name",
        "source_row",
        "source_order",
        "row_number",
        # Direct identity/contact, credentials, and government identifiers are
        # intentionally unavailable through the generic grouping surface.
        "id",
        "record_id",
        "user_id",
        "phone",
        "phone_number",
        "mobile",
        "mobile_number",
        "contact",
        "contact_no",
        "contact_number",
        "telephone",
        "telephone_number",
        "tel",
        "cell",
        "cell_number",
        "whatsapp",
        "whatsapp_number",
        "wa",
        "wa_no",
        "wa_number",
        "w_app",
        "w_app_no",
        "w_app_number",
        "mob",
        "mob_no",
        "mob_number",
        "ph",
        "ph_no",
        "ph_number",
        "email",
        "email_id",
        "mail",
        "mail_id",
        "address",
        "addr",
        "residential_addr",
        "residential_address",
        "home_address",
        "aadhaar",
        "aadhaar_number",
        "aadhar",
        "aadhar_number",
        "pan",
        "pan_number",
        "visa_number",
        "visa_reference",
        "token",
        "password",
        "secret",
    }
)
_UNAVAILABLE_COMPACT_PRIORITY_ALIASES = frozenset(
    alias.replace("_", "") for alias in _UNAVAILABLE_PRIORITY_ALIASES
)


@dataclass(frozen=True, slots=True)
class RoomingPriorityContext:
    """Available descriptors and resolved values keyed by passenger."""

    fields: list[dict[str, str]]
    values_by_passenger: dict[uuid.UUID, dict[str, str | None]]


def normalize_imported_field_key(value: object) -> str:
    """Normalize external spreadsheet headers into stable API keys."""

    raw_value = unicodedata.normalize("NFKC", str(value or ""))
    camel_case_split = re.sub(
        r"(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-z0-9])(?=[A-Z])",
        " ",
        raw_value,
    )
    return "_".join(
        part
        for part in "".join(
            character.casefold() if character.isalnum() else " "
            for character in camel_case_split
        ).split()
        if part
    )


def _is_unavailable_priority(value: object) -> bool:
    normalized = normalize_imported_field_key(value)
    # Compatibility normalization keeps useful Unicode labels intact while a
    # second accent-insensitive projection prevents visually varied identity
    # headers (for example full-width or accented phone labels) bypassing the
    # fail-closed grouping filter.
    security_normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )
    tokens = set(security_normalized.split("_"))
    compact = security_normalized.replace("_", "")
    return (
        not normalized
        or normalized in _UNAVAILABLE_PRIORITY_ALIASES
        or compact in _UNAVAILABLE_COMPACT_PRIORITY_ALIASES
        or bool(
            tokens
            & {
                "aadhaar",
                "aadhar",
                "address",
                "birth",
                "cell",
                "contact",
                "dob",
                "email",
                "gender",
                "hash",
                "mobile",
                "name",
                "pan",
                "passport",
                "password",
                "phone",
                "secret",
                "sex",
                "token",
                "visa",
                "whatsapp",
                "tel",
                "telephone",
            }
        )
        or compact.startswith("gender")
        or compact.endswith("gender")
        or security_normalized.endswith("_addr")
        or any(
            sensitive_compound in compact
            for sensitive_compound in (
                "whatsapp",
                "email",
                "telephone",
                "mobile",
                "phone",
                "contact",
                "address",
                "passport",
                "aadhaar",
                "aadhar",
                "password",
                "secret",
                "token",
            )
        )
        or (
            normalized.startswith("source_")
            and normalized != "source_zone"
        )
    )


def _clean_value(value: object) -> str | None:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized or normalized.casefold() in {"null", "none", "n/a", "na"}:
        return None
    return normalized


def _base_field_definitions(group: ClientGroupModel) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = [
        {"key": "field:client_phone", "label": "Phone Number", "source": "contact"},
        {"key": "field:client_email", "label": "Email ID", "source": "contact"},
        {"key": "field:nationality", "label": "Nationality", "source": "passport"},
        {"key": "field:submission_mode", "label": "Submission Mode", "source": "submission"},
        {"key": "field:family_relation", "label": "Family Relation", "source": "submission"},
        {"key": "field:family_group", "label": "Family / Couple", "source": "submission"},
    ]
    optional = (
        (
            group.agency_dealership_name_enabled,
            "field:agency_dealership_name",
            "Agency/Dealership Name",
        ),
        (group.base_city_enabled, "field:base_city", "Base City"),
        (
            group.ask_nearest_domestic_airport,
            "field:nearest_domestic_airport",
            "Domestic Airport",
        ),
        (
            group.nearest_international_airport_enabled,
            "field:departure_city",
            "International Airport",
        ),
        (group.meal_preference_enabled, "field:meal_preference", "Meal Preference"),
        (group.designation_enabled, "field:designation", "Designation"),
        (
            group.relation_with_qualifier_enabled,
            "field:qualifier_relation",
            "Relation with Qualifier",
        ),
    )
    fields.extend(
        {"key": key, "label": label, "source": "group_field"}
        for enabled, key, label in optional
        if enabled
    )
    for question in group.custom_questions or []:
        label = _clean_value(question.get("label"))
        if (
            question.get("enabled")
            and question.get("id")
            and label
            and not _is_unavailable_priority(label)
        ):
            fields.append(
                {
                    "key": f"custom:{question['id']}",
                    "label": label,
                    "source": "custom_question",
                }
            )
    for detail in group.custom_details or []:
        label = _clean_value(detail.get("label"))
        if (
            detail.get("enabled")
            and detail.get("id")
            and label
            and not _is_unavailable_priority(label)
        ):
            fields.append(
                {
                    "key": f"custom_detail:{detail['id']}",
                    "label": label,
                    "source": "custom_detail",
                }
            )
    return fields


def _humanize_imported_field_label(normalized_key: str) -> str:
    abbreviations = {"id": "ID", "qr": "QR", "vip": "VIP"}
    return " ".join(
        abbreviations.get(part, part.capitalize())
        for part in normalized_key.split("_")
        if part
    )


def _metadata_field_definitions(
    passengers: list[PassportSubmissionModel],
) -> list[dict[str, str]]:
    """Return a deterministic, bounded catalog of safe imported columns."""

    normalized_keys: set[str] = set()
    for passenger in passengers:
        for raw_key in (passenger.staff_metadata or {}):
            normalized = normalize_imported_field_key(raw_key)
            field_key = f"metadata:{normalized}"
            if (
                _is_unavailable_priority(normalized)
                or len(field_key) > MAX_ROOMING_FIELD_KEY_LENGTH
            ):
                continue
            normalized_keys.add(normalized)
    return [
        {
            "key": f"metadata:{normalized}",
            "label": _humanize_imported_field_label(normalized),
            "source": "imported_excel",
        }
        for normalized in sorted(normalized_keys)[:MAX_ROOMING_METADATA_FIELDS]
    ]


_NON_GROUPABLE_FIELD_KEYS = frozenset(
    {
        "field:client_phone",
        "field:client_email",
        "field:family_group",
    }
)


def is_rooming_roster_field(field: dict[str, str]) -> bool:
    """Return whether a priority field is safe for the generic roster UI."""

    key = field.get("key", "")
    label = field.get("label", "")
    return (
        bool(key)
        and key not in _NON_GROUPABLE_FIELD_KEYS
        and not _is_unavailable_priority(label)
    )


def _deduplicate_labels(fields: list[dict[str, str]]) -> list[dict[str, str]]:
    used: set[str] = set()
    result: list[dict[str, str]] = []
    for field in fields:
        label = _clean_value(field["label"])
        if not label:
            continue
        candidate = label[:120]
        suffix_index = 1
        while candidate.casefold() in used:
            source = field["source"].replace("_", " ").title()
            suffix = f" ({source})" if suffix_index == 1 else f" ({source} {suffix_index})"
            candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
            suffix_index += 1
        used.add(candidate.casefold())
        result.append({**field, "label": candidate})
    return result


def _submission_field_values(
    passenger: PassportSubmissionModel,
    fields: list[dict[str, str]],
) -> dict[str, str | None]:
    passport_fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    staff_metadata = passenger.staff_metadata or {}
    normalized_staff_metadata = {
        normalize_imported_field_key(raw_key): raw_value
        for raw_key, raw_value in staff_metadata.items()
    }
    custom_answers = {
        f"custom:{answer.get('question_id')}": _clean_value(answer.get("value"))
        for answer in passenger.custom_answers or []
        if answer.get("question_id")
    }
    custom_details = {
        f"custom_detail:{answer.get('detail_id')}": _clean_value(answer.get("value"))
        for answer in passenger.custom_detail_answers or []
        if answer.get("detail_id")
    }
    family_group = (
        _clean_value(passenger.family_head_name)
        or (str(passenger.family_group_id) if passenger.family_group_id else None)
    )
    standard_values: dict[str, object] = {
        "field:client_phone": passenger.client_phone,
        "field:client_email": passenger.client_email,
        "field:nationality": passport_fields.get("nationality"),
        "field:submission_mode": passenger.submission_mode.replace("_", " ").title(),
        "field:family_relation": passenger.family_relation,
        "field:family_group": family_group,
        "field:agency_dealership_name": (
            passport_fields.get("agency_dealership_name")
            or staff_metadata.get("agency_dealership_name")
        ),
        "field:base_city": passport_fields.get("base_city") or staff_metadata.get("base_city"),
        "field:nearest_domestic_airport": passenger.nearest_domestic_airport,
        "field:departure_city": passenger.departure_city,
        "field:meal_preference": (
            passport_fields.get("meal_preference") or staff_metadata.get("meal_preference")
        ),
        "field:designation": (
            passport_fields.get("designation") or staff_metadata.get("designation")
        ),
        "field:qualifier_relation": (
            passenger.qualifier_relation_label
            if passenger.qualifier_enabled_snapshot
            else None
        ),
    }
    values: dict[str, str | None] = {}
    for field in fields:
        key = field["key"]
        if key.startswith("custom_detail:"):
            values[key] = custom_details.get(key)
        elif key.startswith("custom:"):
            values[key] = custom_answers.get(key)
        elif key.startswith("metadata:"):
            values[key] = _clean_value(
                normalized_staff_metadata.get(key.removeprefix("metadata:"))
            )
        elif key.startswith("field:"):
            values[key] = _clean_value(standard_values.get(key))
    return values


def _recipient_value(row: SubmissionMatchRow, normalized_key: str) -> str | None:
    values: dict[str, str] = {}
    for field_set in sorted(row.recipient_fields, key=lambda item: str(item.recipient_id)):
        for raw_key, raw_value in field_set.fields.items():
            if normalize_imported_field_key(raw_key) != normalized_key:
                continue
            cleaned = _clean_value(raw_value)
            if cleaned:
                values.setdefault(cleaned.casefold(), cleaned)
    return next(iter(values.values())) if len(values) == 1 else None


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
    """Return the selectable field catalog and deterministic passenger values."""

    base_fields = _base_field_definitions(group)
    metadata_fields = _metadata_field_definitions(passengers)
    local_fields = _deduplicate_labels([*base_fields, *metadata_fields])
    if requested_keys is not None and not any(
        key.startswith("whatsapp:") for key in requested_keys
    ):
        value_fields_by_key = {
            field["key"]: field
            for field in [*local_fields, *(required_fields or [])]
            if field["key"] in requested_keys
        }
        return RoomingPriorityContext(
            fields=local_fields,
            values_by_passenger=(
                {
                    passenger.id: _submission_field_values(
                        passenger,
                        list(value_fields_by_key.values()),
                    )
                    for passenger in passengers
                }
                if resolve_values
                else {}
            ),
        )

    linked_statement = (
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
    if lock_inputs:
        linked_statement = linked_statement.with_for_update(read=True)
    linked_result = await session.execute(linked_statement)
    linked_broadcasts: dict[uuid.UUID, str] = {
        row[0]: row[1] for row in linked_result.all()
    }
    if not linked_broadcasts:
        value_fields_by_key = {
            field["key"]: field
            for field in [*local_fields, *(required_fields or [])]
            if requested_keys is None or field["key"] in requested_keys
        }
        return RoomingPriorityContext(
            fields=local_fields,
            values_by_passenger=(
                {
                    passenger.id: _submission_field_values(
                        passenger,
                        list(value_fields_by_key.values()),
                    )
                    for passenger in passengers
                }
                if resolve_values
                else {}
            ),
        )

    recipient_statement = select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(linked_broadcasts),
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    if lock_inputs:
        recipient_statement = recipient_statement.with_for_update(read=True)
    recipient_result = await session.execute(recipient_statement)
    recipients = list(recipient_result.scalars().all())
    imported_labels: dict[str, str] = {}
    for recipient in recipients:
        for raw_key in (recipient.imported_fields or {}):
            normalized = normalize_imported_field_key(raw_key)
            field_key = f"whatsapp:{normalized}"
            if (
                not normalized
                or _is_unavailable_priority(raw_key)
                or len(field_key) > MAX_ROOMING_FIELD_KEY_LENGTH
            ):
                continue
            imported_labels.setdefault(normalized, str(raw_key))
    whatsapp_fields = [
        {
            "key": f"whatsapp:{normalized}",
            "label": label,
            "source": "whatsapp",
        }
        for normalized, label in sorted(
            imported_labels.items(),
            key=lambda item: (item[1].casefold(), item[0]),
        )
    ]
    fields = _deduplicate_labels(
        [*base_fields, *metadata_fields, *whatsapp_fields]
    )
    value_fields_by_key = {
        field["key"]: field
        for field in [*fields, *(required_fields or [])]
        if requested_keys is None or field["key"] in requested_keys
    }
    values_by_passenger = (
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
    whatsapp_keys = [
        field["key"].removeprefix("whatsapp:")
        for field in value_fields_by_key.values()
        if field["key"].startswith("whatsapp:")
    ]
    if (
        not resolve_values
        or not whatsapp_keys
        or not recipients
        or not passengers
    ):
        return RoomingPriorityContext(
            fields=fields,
            values_by_passenger=values_by_passenger,
        )

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
        for recipient in recipients
    ]
    comparison_submissions = [
        SubmissionForComparison(
            id=passenger.id,
            name=passenger.client_name,
            client_phone=passenger.client_phone,
            family_head_phone=passenger.family_head_phone,
            updated_at=passenger.updated_at,
            client_email=passenger.client_email,
            family_head_email=passenger.family_head_email,
            confirmed_fields=dict(passenger.confirmed_fields or {}),
            extracted_fields=dict(passenger.extracted_fields or {}),
            staff_metadata=dict(passenger.staff_metadata or {}),
        )
        for passenger in passengers
    ]
    rows, _ = compare_group_submissions(comparison_recipients, comparison_submissions)
    whatsapp_keys = list(dict.fromkeys(whatsapp_keys))
    for row in rows:
        if row.status not in {"submitted", "multiple_submissions"}:
            continue
        resolved = {
            f"whatsapp:{normalized}": _recipient_value(row, normalized)
            for normalized in whatsapp_keys
        }
        for passenger_id in row.submission_ids:
            if passenger_id in values_by_passenger:
                values_by_passenger[passenger_id].update(resolved)
    return RoomingPriorityContext(fields=fields, values_by_passenger=values_by_passenger)
