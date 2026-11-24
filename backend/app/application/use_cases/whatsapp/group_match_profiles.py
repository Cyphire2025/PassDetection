"""Roster and submission evidence profiles with explicit source precedence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.application.use_cases.whatsapp.group_match_fields import (
    _EMAIL_KEYS,
    _GIVEN_NAME_KEYS,
    _NAME_KEYS,
    _PASSPORT_KEYS,
    _PHONE_KEYS,
    _STAFF_CODE_KEYS,
    _SURNAME_KEYS,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _mapping_field_values,
    _mapping_values,
    _normalized_email,
    _normalized_identifier,
    _normalized_key,
    _normalized_name,
    _normalized_values,
    _selected_field_normalizer,
    normalize_matching_field_key,
)
from app.application.use_cases.whatsapp.group_match_types import (
    IdentityEvidenceValues,
    RecipientForComparison,
    SubmissionForComparison,
    _IdentityProfile,
    _LogicalRecipient,
)
from app.application.use_cases.whatsapp.imported_broadcast_phone import (
    explicit_imported_broadcast_phone,
    imported_phone_column_priority,
)


def _passport_fields(submission: SubmissionForComparison) -> dict[str, object]:
    # Merge on the same canonical key used for matching, so a confirmed
    # correction replaces a stale extracted alias (for example ``dob`` versus
    # ``date_of_birth``) instead of leaving both values eligible.
    fields: dict[str, object] = {}
    for mapping in (submission.extracted_fields, submission.confirmed_fields):
        for raw_key, value in (mapping or {}).items():
            if key := normalize_matching_field_key(raw_key):
                fields[key] = value
    return fields


def _composed_names(mapping: Mapping[str, object]) -> list[str]:
    given_values = _mapping_values(mapping, _GIVEN_NAME_KEYS)
    surname_values = _mapping_values(mapping, _SURNAME_KEYS)
    names: list[str] = []
    for given in given_values or [""]:
        for surname in surname_values or [""]:
            combined = " ".join(part for part in (str(given).strip(), str(surname).strip()) if part)
            if combined:
                names.append(combined)
    return names


def _recipient_profile(
    recipients: tuple[RecipientForComparison, ...],
) -> _IdentityProfile:
    legacy_recipients = tuple(
        recipient for recipient in recipients if recipient.matching_field_keys is None
    )
    fields = [dict(recipient.imported_fields or {}) for recipient in legacy_recipients]
    selected_values: dict[str, set[str]] = defaultdict(set)
    for recipient in recipients:
        if recipient.matching_field_keys is None:
            continue
        imported_fields = dict(recipient.imported_fields or {})
        for raw_field_key in recipient.matching_field_keys:
            field_key = normalize_matching_field_key(raw_field_key)
            # Read only the stored heading the operator selected. Aliases are
            # applied to the comparison key below, not to independent roster
            # columns that were never selected.
            raw_values: list[object] = list(_mapping_field_values(imported_fields, raw_field_key))
            if field_key == "name":
                raw_values.insert(0, recipient.name)
            elif field_key == "phone_number":
                raw_values.insert(0, recipient.phone)
            normalized = _normalized_values(
                raw_values,
                _selected_field_normalizer(field_key),
            )
            selected_values[field_key].update(normalized)
    return _IdentityProfile(
        phones=_normalized_values(
            [
                *(recipient.phone for recipient in legacy_recipients),
                *(value for mapping in fields for value in _mapping_values(mapping, _PHONE_KEYS)),
            ],
            normalize_whatsapp_phone,
        ),
        emails=_normalized_values(
            (value for mapping in fields for value in _mapping_values(mapping, _EMAIL_KEYS)),
            _normalized_email,
        ),
        passport_numbers=_normalized_values(
            (value for mapping in fields for value in _mapping_values(mapping, _PASSPORT_KEYS)),
            _normalized_identifier,
        ),
        staff_codes=_normalized_values(
            (value for mapping in fields for value in _mapping_values(mapping, _STAFF_CODE_KEYS)),
            _normalized_identifier,
        ),
        names=_normalized_values(
            [
                *(recipient.name for recipient in legacy_recipients),
                *(value for mapping in fields for value in _mapping_values(mapping, _NAME_KEYS)),
                *(name for mapping in fields for name in _composed_names(mapping)),
            ],
            _normalized_name,
        ),
        selected_fields={
            key: frozenset(values) for key, values in sorted(selected_values.items()) if values
        },
    )


def _submission_field_map(
    submission: SubmissionForComparison,
) -> dict[str, list[object]]:
    values: dict[str, list[object]] = defaultdict(list)

    def add(key: object, value: object) -> None:
        if value is None or str(value).strip() == "":
            return
        canonical = normalize_matching_field_key(key)
        if canonical:
            values[canonical].append(value)

    add("name", submission.name)
    add("phone_number", submission.client_phone)
    add("phone_number", submission.family_head_phone)
    add("email", submission.client_email)
    add("email", submission.family_head_email)
    add("departure_city", submission.departure_city)
    add("nearest_international_airport", submission.departure_city)
    add("nearest_domestic_airport", submission.nearest_domestic_airport)
    add("family_relation", submission.family_relation)
    add("family_gender", submission.family_gender)
    add("family_head_name", submission.family_head_name)
    # Confirmed client/staff corrections supersede stale OCR values per key.
    staff_fields = dict(submission.staff_metadata or {})
    passport_fields = _passport_fields(submission)
    layered_fields: dict[str, object] = {}
    if not submission.has_public_collection_contact:
        imported_phone, _ = explicit_imported_broadcast_phone(staff_fields)
        add("phone_number", imported_phone)
    for key, value in staff_fields.items():
        if imported_phone_column_priority(key) is not None:
            # Only the winning explicit source may contribute; a stale Upload
            # Phone must not revive a superseded verified/public destination.
            continue
        if not _normalized_key(key).endswith("_label"):
            if canonical := normalize_matching_field_key(key):
                layered_fields[canonical] = value
    # Confirmed/extracted passport fields use the same precedence as the
    # legacy profile and replace stale staff metadata for the canonical key.
    layered_fields.update(passport_fields)
    for key, value in layered_fields.items():
        add(key, value)
    for value_key, label_key in (
        ("agent_employee_code", "agent_employee_code_label"),
        ("agency_dealership_name", "agency_dealership_name_label"),
    ):
        configured_label = staff_fields.get(label_key)
        configured_value = passport_fields.get(value_key, staff_fields.get(value_key))
        if configured_label and configured_value not in (None, ""):
            add(configured_label, configured_value)
    for composed_name in _composed_names(passport_fields):
        add("name", composed_name)
    for snapshot in (*submission.custom_answers, *submission.custom_detail_answers):
        label = snapshot.get("label")
        value = snapshot.get("value")
        add(label, value)
    return dict(values)


def _submission_profile(
    submission: SubmissionForComparison,
) -> _IdentityProfile:
    passport_fields = _passport_fields(submission)
    staff_fields = {
        **dict(submission.staff_metadata or {}),
        **passport_fields,
    }
    entered_names = _normalized_values([submission.name], _normalized_name)
    passport_names = _normalized_values(
        [
            *_mapping_values(passport_fields, _NAME_KEYS),
            *_composed_names(passport_fields),
        ],
        _normalized_name,
    )
    selected_fields: dict[str, frozenset[str]] = {}
    for field_key, raw_values in _submission_field_map(submission).items():
        normalized = _normalized_values(
            raw_values,
            _selected_field_normalizer(field_key),
        )
        if normalized:
            selected_fields[field_key] = normalized
    return _IdentityProfile(
        phones=_normalized_values(
            [submission.client_phone, submission.family_head_phone],
            normalize_whatsapp_phone,
        ),
        emails=_normalized_values(
            [submission.client_email, submission.family_head_email],
            _normalized_email,
        ),
        passport_numbers=_normalized_values(
            _mapping_values(passport_fields, _PASSPORT_KEYS),
            _normalized_identifier,
        ),
        staff_codes=_normalized_values(
            _mapping_values(staff_fields, _STAFF_CODE_KEYS),
            _normalized_identifier,
        ),
        names=entered_names | passport_names,
        entered_names=entered_names,
        passport_names=passport_names,
        selected_fields=selected_fields,
    )


def recipient_identity_evidence(
    recipients: Iterable[RecipientForComparison],
) -> IdentityEvidenceValues:
    """Return evidence normalized by the authoritative recipient matcher."""

    ordered = tuple(sorted(recipients, key=_recipient_sort_key))
    profile = _recipient_profile(ordered)
    return IdentityEvidenceValues(
        phones=profile.phones,
        emails=profile.emails,
        passport_numbers=profile.passport_numbers,
        staff_codes=profile.staff_codes,
        names=profile.names,
        selected_fields=profile.selected_fields,
    )


def submission_identity_evidence(
    submission: SubmissionForComparison,
) -> IdentityEvidenceValues:
    """Return evidence normalized by the authoritative submission matcher."""

    profile = _submission_profile(submission)
    return IdentityEvidenceValues(
        phones=profile.phones,
        emails=profile.emails,
        passport_numbers=profile.passport_numbers,
        staff_codes=profile.staff_codes,
        names=profile.names,
        selected_fields=profile.selected_fields,
    )


def _recipient_sort_key(recipient: RecipientForComparison) -> tuple[str, str]:
    return (str(recipient.broadcast_id), str(recipient.id))


def _submission_sort_key(
    submission: SubmissionForComparison,
) -> tuple[datetime, str]:
    return (_timestamp_key(submission.updated_at), str(submission.id))


def _timestamp_key(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _logical_recipients(
    recipients: list[RecipientForComparison],
) -> list[_LogicalRecipient]:
    groups: dict[str, list[RecipientForComparison]] = defaultdict(list)
    for recipient in recipients:
        normalized = normalize_whatsapp_phone(recipient.phone)
        key = normalized or f"invalid:{recipient.id}"
        groups[key].append(recipient)
    return [
        _LogicalRecipient(
            recipients=tuple(sorted(group, key=_recipient_sort_key)),
            profile=_recipient_profile(tuple(sorted(group, key=_recipient_sort_key))),
        )
        for _, group in sorted(groups.items())
    ]
