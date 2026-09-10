"""Deterministic identity comparison for WhatsApp recipients and submissions.

Exact contact and identifier evidence can assign a submission automatically.
Names remain useful evidence, but a name alone never creates an automatic
match under the legacy policy. Explicit per-link field selections are an
operator-authored policy: an exact normalized match on *any* selected field is
strong evidence. A submission is assigned to at most one logical recipient;
collisions and contradictory evidence are surfaced for staff review.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TypeVar

from app.application.use_cases.whatsapp.contact_normalization import (
    clean_whatsapp_name,
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.group_submission_policy import (
    duplicate_passport_submission_ids,
    selected_field_value_uniqueness,
)

_EMAIL_KEYS = frozenset({"email", "email_address", "e_mail", "mail"})
_PASSPORT_KEYS = frozenset({"passport", "passport_no", "passport_number", "passportnumber"})
_STAFF_CODE_KEYS = frozenset(
    {
        "employee_code",
        "staff_code",
        "staff_id",
        "staffcode",
    }
)
_GIVEN_NAME_KEYS = frozenset({"first_name", "given_name", "given_names"})
_SURNAME_KEYS = frozenset({"family_name", "last_name", "surname"})
_NAME_KEYS = frozenset(
    {
        "client_name",
        "employee_name",
        "full_name",
        "name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "staffname",
    }
)
_PHONE_KEYS = frozenset(
    {
        "contact",
        "contact_number",
        "mobile",
        "mobile_number",
        "phone",
        "phone_number",
        "telephone",
        "whatsapp",
        "whatsapp_number",
    }
)
_STRONG_EVIDENCE_WEIGHTS = {
    "passport_number": 120,
    "staff_code": 110,
    "email": 100,
    "phone": 100,
}
_NAME_EVIDENCE_WEIGHT = 20
_SELECTED_FIELD_EVIDENCE_WEIGHT = 100
_PRIVATE_SELECTED_FIELD_KEYS = frozenset(
    {
        "phone_number",
        "email",
        "passport_number",
        "staff_code",
    }
)
_MATCH_FIELD_KEY_ALIASES = {
    "client_name": "name",
    "contact_name": "name",
    "employee_name": "name",
    "full_name": "name",
    "passenger_name": "name",
    "recipient_name": "name",
    "staff_name": "name",
    "staffname": "name",
    "contact": "phone_number",
    "contact_no": "phone_number",
    "contact_number": "phone_number",
    "mobile": "phone_number",
    "mobile_no": "phone_number",
    "mobile_number": "phone_number",
    "phone": "phone_number",
    "phone_no": "phone_number",
    "telephone": "phone_number",
    "whatsapp": "phone_number",
    "whatsapp_no": "phone_number",
    "whatsapp_number": "phone_number",
    "email_address": "email",
    "e_mail": "email",
    "mail": "email",
    "passport": "passport_number",
    "passport_no": "passport_number",
    "passportnumber": "passport_number",
    "employee_code": "staff_code",
    "staff_id": "staff_code",
    "staffcode": "staff_code",
    "producer_code": "agent_employee_code",
    "agent_code": "agent_employee_code",
    "agentcode": "agent_employee_code",
    "dealer_code": "agent_employee_code",
    "agency_name": "agency_dealership_name",
    "agent_company": "agency_dealership_name",
    "company": "agency_dealership_name",
    "company_name": "agency_dealership_name",
    "birth_date": "date_of_birth",
    "birthdate": "date_of_birth",
    "dob": "date_of_birth",
}
_MATCH_DATE_FIELD_KEYS = frozenset(
    {
        "date_of_birth",
        "birth_date",
        "birthdate",
        "dob",
    }
)
_MATCH_IDENTIFIER_FIELD_KEYS = frozenset(
    {
        "agent_employee_code",
        "employee_code",
        "passport",
        "passport_no",
        "passport_number",
        "passportnumber",
        "staff_code",
        "staff_id",
    }
)
_MISSING_MATCH_VALUES = frozenset(
    {
        "",
        "n a",
        "na",
        "nil",
        "none",
        "not applicable",
        "not available",
        "null",
    }
)
_MappingValue = TypeVar("_MappingValue")
_NormalizedInput = TypeVar("_NormalizedInput")


@dataclass(frozen=True)
class RecipientForComparison:
    id: uuid.UUID
    broadcast_id: uuid.UUID
    broadcast_name: str
    name: str | None
    phone: str | None
    updated_at: datetime
    imported_fields: dict[str, str] = field(default_factory=dict)
    # ``None`` preserves the historical phone/email/passport/staff/name policy.
    # A non-empty tuple is the explicit policy configured on this broadcast
    # link and uses OR semantics across the selected fields.
    matching_field_keys: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SubmissionForComparison:
    id: uuid.UUID
    name: str
    client_phone: str | None
    family_head_phone: str | None
    updated_at: datetime
    client_email: str | None = None
    family_head_email: str | None = None
    confirmed_fields: dict[str, object] = field(default_factory=dict)
    extracted_fields: dict[str, object] = field(default_factory=dict)
    staff_metadata: dict[str, object] = field(default_factory=dict)
    custom_answers: tuple[Mapping[str, object], ...] = ()
    custom_detail_answers: tuple[Mapping[str, object], ...] = ()
    departure_city: str | None = None
    nearest_domestic_airport: str | None = None
    family_relation: str | None = None
    family_gender: str | None = None
    family_head_name: str | None = None


@dataclass(frozen=True)
class MatchEvidence:
    submission_id: uuid.UUID
    kind: str
    recipient_value: str
    submission_value: str
    weight: int
    # ``None`` denotes legacy/synthetic evidence whose historical semantics
    # are preserved. Selected-field evidence is explicit: only a unique value
    # from a private-grade field is safe for sensitive delivery decisions.
    private_identity_confirmed: bool | None = None


@dataclass(frozen=True)
class RecipientFieldSet:
    recipient_id: uuid.UUID
    fields: dict[str, str]


@dataclass(frozen=True)
class SubmissionMatchRow:
    status: str
    match_basis: str | None
    normalized_phone: str | None
    recipient_ids: tuple[uuid.UUID, ...]
    submission_ids: tuple[uuid.UUID, ...]
    broadcast_ids: tuple[uuid.UUID, ...]
    broadcast_names: tuple[str, ...]
    recipient_names: tuple[str, ...]
    submission_names: tuple[str, ...]
    updated_at: datetime
    confidence: str = "none"
    match_evidence: tuple[MatchEvidence, ...] = ()
    candidate_submission_ids: tuple[uuid.UUID, ...] = ()
    recipient_fields: tuple[RecipientFieldSet, ...] = ()
    resolution_id: uuid.UUID | None = None
    duplicate_submission_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class SubmissionMatchSummary:
    total_recipients: int
    submitted_count: int
    not_submitted_count: int
    multiple_submission_count: int
    matched_submission_count: int
    needs_review_count: int = 0
    needs_review_submission_count: int = 0
    unmatched_submission_count: int = 0
    replacement_count: int = 0
    rejected_upload_count: int = 0


@dataclass(frozen=True)
class _IdentityProfile:
    phones: frozenset[str] = frozenset()
    emails: frozenset[str] = frozenset()
    passport_numbers: frozenset[str] = frozenset()
    staff_codes: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()
    entered_names: frozenset[str] = frozenset()
    passport_names: frozenset[str] = frozenset()
    selected_fields: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class IdentityEvidenceValues:
    """Normalized values that can connect one member of a matching cluster.

    The public projection deliberately mirrors the exact comparison
    normalizers.  Targeted mobile reconciliation uses it to discover the
    complete connected component before running the authoritative matcher;
    it does not implement a second matching policy.
    """

    phones: frozenset[str] = frozenset()
    emails: frozenset[str] = frozenset()
    passport_numbers: frozenset[str] = frozenset()
    staff_codes: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()
    selected_fields: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @property
    def all_values(self) -> frozenset[str]:
        selected = frozenset(value for values in self.selected_fields.values() for value in values)
        return (
            self.phones
            | self.emails
            | self.passport_numbers
            | self.staff_codes
            | self.names
            | selected
        )


@dataclass(frozen=True)
class _LogicalRecipient:
    recipients: tuple[RecipientForComparison, ...]
    profile: _IdentityProfile


@dataclass(frozen=True)
class _PairEvidence:
    recipient_index: int
    submission_index: int
    evidence: tuple[MatchEvidence, ...]
    score: int
    auto_match: bool


def _normalized_key(value: object) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text)).strip("_")


def normalize_matching_field_key(value: object) -> str:
    """Return the stable key used to join an imported heading to an answer.

    The import layer already stores snake-case keys. Keeping this normalizer in
    the matcher also supports older/manual payloads and common aliases such as
    ``DOB`` versus the passport field ``date_of_birth``.
    """

    normalized = _normalized_key(value)
    return _MATCH_FIELD_KEY_ALIASES.get(normalized, normalized)


def _normalized_name(value: object) -> str | None:
    cleaned = clean_whatsapp_name(value)
    if not cleaned:
        return None
    compatible = unicodedata.normalize("NFKC", cleaned).casefold()
    normalized = "".join(
        character if character.isalnum() else " " for character in compatible
    ).strip()
    return " ".join(normalized.split()) or None


def _normalized_email(value: object) -> str | None:
    text = str(value or "").strip().casefold()
    if not text or "@" not in text:
        return None
    local, separator, domain = text.partition("@")
    if not separator or not local or "." not in domain:
        return None
    return f"{local}@{domain}"


def _normalized_identifier(value: object) -> str | None:
    normalized = re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
    return normalized or None


def _normalized_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    iso_candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date().isoformat()
    except ValueError:
        pass
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return _normalized_identifier(text)


def _normalized_generic(value: object) -> str | None:
    compatible = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = "".join(character if character.isalnum() else " " for character in compatible)
    normalized = " ".join(normalized.split())
    if normalized in _MISSING_MATCH_VALUES:
        return None
    return normalized


def _normalized_phone(value: object) -> str | None:
    return normalize_whatsapp_phone(None if value is None else str(value))


def _selected_field_normalizer(field_key: str) -> Callable[[object], str | None]:
    canonical = normalize_matching_field_key(field_key)
    if canonical == "phone_number":
        return _normalized_phone
    if canonical == "email":
        return _normalized_email
    if canonical == "name":
        return _normalized_name
    if canonical in _MATCH_DATE_FIELD_KEYS or "date_of_birth" in canonical:
        return _normalized_date
    if (
        canonical in _MATCH_IDENTIFIER_FIELD_KEYS
        or canonical.endswith("_code")
        or canonical.endswith("_id")
    ):
        return _normalized_identifier
    return _normalized_generic


def _mapping_values(
    mapping: Mapping[str, _MappingValue],
    keys: frozenset[str],
) -> list[_MappingValue]:
    values: list[_MappingValue] = []
    for raw_key, value in mapping.items():
        normalized = _normalized_key(raw_key)
        base_key = re.sub(r"_\d+$", "", normalized)
        if normalized in keys or base_key in keys:
            values.append(value)
    return values


def _mapping_field_values(
    mapping: Mapping[str, _MappingValue],
    field_key: str,
) -> list[_MappingValue]:
    selected_key = _normalized_key(field_key)
    values: list[_MappingValue] = []
    for raw_key, value in mapping.items():
        normalized = _normalized_key(raw_key)
        # Alternate ``_2`` keys are created only when the importer records the
        # base key in duplicate_conflicting_fields. Do not strip suffixes from
        # legitimate headings such as ``terminal_2``.
        conflicting = {
            _normalized_key(item)
            for item in str(mapping.get("duplicate_conflicting_fields", "")).split(",")
            if _normalized_key(item)
        }
        base_key = (
            re.sub(r"_\d+$", "", normalized)
            if re.sub(r"_\d+$", "", normalized) in conflicting
            else normalized
        )
        if normalized == selected_key or base_key == selected_key:
            values.append(value)
    return values


def _normalized_values(
    values: Iterable[_NormalizedInput],
    normalizer: Callable[[_NormalizedInput], str | None],
) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        # Placeholder cells must never become strong exact-match tokens such
        # as ``NA`` or ``NOTAVAILABLE`` under identifier/date normalizers.
        if _normalized_generic(value) is None:
            continue
        item = normalizer(value)
        if item:
            normalized.add(item)
    return frozenset(normalized)


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
    for key, value in staff_fields.items():
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


def _evidence_item(
    *,
    submission_id: uuid.UUID,
    kind: str,
    recipient_values: frozenset[str],
    submission_values: frozenset[str],
    weight: int,
    preferred_values: frozenset[str] = frozenset(),
    association_values: frozenset[str] = frozenset(),
    private_identity_kind: bool | None = None,
) -> MatchEvidence | None:
    shared = sorted(recipient_values & submission_values)
    if not shared:
        return None
    # Evidence stores one representative value. For selected fields, prefer a
    # value that is unique on both sides so the persisted explanation reflects
    # the value that actually made the pair safe to auto-assign.
    association_value = next((item for item in shared if item in association_values), shared[0])
    value = next((item for item in shared if item in preferred_values), association_value)
    return MatchEvidence(
        submission_id=submission_id,
        kind=kind,
        recipient_value=value,
        submission_value=value,
        weight=weight,
        private_identity_confirmed=(
            None
            if private_identity_kind is None
            else private_identity_kind and value in preferred_values
        ),
    )


def _pair_evidence(
    *,
    recipient_index: int,
    recipient: _LogicalRecipient,
    submission_index: int,
    submission: SubmissionForComparison,
    submission_profile: _IdentityProfile,
    unique_compound_names: frozenset[str],
    unique_selected_values: frozenset[tuple[str, str]],
    roster_unique_selected_values: frozenset[tuple[str, str]],
) -> _PairEvidence | None:
    evidence = [
        item
        for item in (
            _evidence_item(
                submission_id=submission.id,
                kind="phone",
                recipient_values=recipient.profile.phones,
                submission_values=submission_profile.phones,
                weight=_STRONG_EVIDENCE_WEIGHTS["phone"],
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="email",
                recipient_values=recipient.profile.emails,
                submission_values=submission_profile.emails,
                weight=_STRONG_EVIDENCE_WEIGHTS["email"],
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="passport_number",
                recipient_values=recipient.profile.passport_numbers,
                submission_values=submission_profile.passport_numbers,
                weight=_STRONG_EVIDENCE_WEIGHTS["passport_number"],
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="staff_code",
                recipient_values=recipient.profile.staff_codes,
                submission_values=submission_profile.staff_codes,
                weight=_STRONG_EVIDENCE_WEIGHTS["staff_code"],
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="entered_name",
                recipient_values=recipient.profile.names,
                submission_values=submission_profile.entered_names,
                weight=_NAME_EVIDENCE_WEIGHT,
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="passport_name",
                recipient_values=recipient.profile.names,
                submission_values=submission_profile.passport_names,
                weight=_NAME_EVIDENCE_WEIGHT,
            ),
        )
        if item is not None
    ]
    for field_key, recipient_values in sorted(recipient.profile.selected_fields.items()):
        unique_values = frozenset(
            value for value in recipient_values if (field_key, value) in unique_selected_values
        )
        item = _evidence_item(
            submission_id=submission.id,
            kind=field_key,
            recipient_values=recipient_values,
            submission_values=submission_profile.selected_fields.get(
                field_key,
                frozenset(),
            ),
            weight=_SELECTED_FIELD_EVIDENCE_WEIGHT,
            preferred_values=unique_values,
            association_values=frozenset(
                value for value in recipient_values
                if (field_key, value) in roster_unique_selected_values
            ),
            private_identity_kind=field_key in _PRIVATE_SELECTED_FIELD_KEYS,
        )
        if item is not None:
            evidence.append(item)
    if not evidence:
        return None
    # A selected heading may canonicalize to a legacy evidence name such as
    # ``email`` or ``staff_code``. Determine legacy strength from its dedicated
    # profile, not the display kind. Roster association may use roster-only
    # uniqueness; private evidence above still requires uniqueness on both sides.
    strong = any(
        (
            bool(recipient.profile.phones & submission_profile.phones),
            bool(recipient.profile.emails & submission_profile.emails),
            bool(recipient.profile.passport_numbers & submission_profile.passport_numbers),
            bool(recipient.profile.staff_codes & submission_profile.staff_codes),
        )
    )
    selected = any(
        item.kind in recipient.profile.selected_fields
        and (
            (item.kind, item.recipient_value) in unique_selected_values
            or (item.kind, item.recipient_value) in roster_unique_selected_values
        )
        for item in evidence
    )
    name_intersection = (
        recipient.profile.names
        & submission_profile.entered_names
        & submission_profile.passport_names
    )
    unique_compound = bool(name_intersection & unique_compound_names)
    return _PairEvidence(
        recipient_index=recipient_index,
        submission_index=submission_index,
        evidence=tuple(sorted(evidence, key=lambda item: (-item.weight, item.kind))),
        score=sum(item.weight for item in evidence),
        auto_match=strong or selected or unique_compound,
    )


def _unique_compound_names(
    recipients: list[_LogicalRecipient],
    submission_profiles: list[_IdentityProfile],
) -> frozenset[str]:
    recipient_frequency: dict[str, int] = defaultdict(int)
    submission_frequency: dict[str, int] = defaultdict(int)
    for recipient in recipients:
        for name in recipient.profile.names:
            recipient_frequency[name] += 1
    for profile in submission_profiles:
        for name in profile.entered_names & profile.passport_names:
            submission_frequency[name] += 1
    return frozenset(
        name
        for name, count in recipient_frequency.items()
        if count == 1 and submission_frequency.get(name) == 1
    )


def _submission_evidence_indexes(
    profiles: list[_IdentityProfile],
) -> tuple[
    dict[str, set[int]],
    dict[str, set[int]],
    dict[str, set[int]],
    dict[str, set[int]],
    dict[str, set[int]],
    dict[str, dict[str, set[int]]],
]:
    """Invert exact evidence once instead of scanning every recipient/submission pair."""

    phones: dict[str, set[int]] = defaultdict(set)
    emails: dict[str, set[int]] = defaultdict(set)
    passports: dict[str, set[int]] = defaultdict(set)
    staff_codes: dict[str, set[int]] = defaultdict(set)
    names: dict[str, set[int]] = defaultdict(set)
    selected_fields: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for index, profile in enumerate(profiles):
        for value in profile.phones:
            phones[value].add(index)
        for value in profile.emails:
            emails[value].add(index)
        for value in profile.passport_numbers:
            passports[value].add(index)
        for value in profile.staff_codes:
            staff_codes[value].add(index)
        for value in profile.entered_names | profile.passport_names:
            names[value].add(index)
        for field_key, values in profile.selected_fields.items():
            for value in values:
                selected_fields[field_key][value].add(index)
    return phones, emails, passports, staff_codes, names, selected_fields


def _duplicate_submission_ids(
    submissions: list[SubmissionForComparison],
) -> tuple[uuid.UUID, ...]:
    identities: list[tuple[uuid.UUID, frozenset[str], str | None]] = []
    for submission in submissions:
        fields = _passport_fields(submission)
        passports = _normalized_values(
            _mapping_values(fields, _PASSPORT_KEYS), _normalized_identifier,
        )
        birth_dates = _normalized_values([fields.get("date_of_birth")], _normalized_date)
        identities.append((submission.id, passports, next(iter(birth_dates), None)))
    return duplicate_passport_submission_ids(identities)


def _candidate_submission_indexes(
    profile: _IdentityProfile,
    evidence_indexes: tuple[
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, dict[str, set[int]]],
    ],
) -> set[int]:
    candidates: set[int] = set()
    value_groups = (
        (profile.phones, evidence_indexes[0]),
        (profile.emails, evidence_indexes[1]),
        (profile.passport_numbers, evidence_indexes[2]),
        (profile.staff_codes, evidence_indexes[3]),
        (profile.names, evidence_indexes[4]),
    )
    for values, index in value_groups:
        for value in values:
            candidates.update(index.get(value, ()))
    for field_key, values in profile.selected_fields.items():
        index = evidence_indexes[5].get(field_key, {})
        for value in values:
            candidates.update(index.get(value, ()))
    return candidates


def _same_identity_basis(matches: list[_PairEvidence]) -> bool:
    if len(matches) < 2:
        return True
    evidence_sets = [
        {
            (item.kind, item.recipient_value)
            for item in match.evidence
            if item.kind in _STRONG_EVIDENCE_WEIGHTS
            or item.weight == _SELECTED_FIELD_EVIDENCE_WEIGHT
        }
        for match in matches
    ]
    common = set.intersection(*evidence_sets) if evidence_sets else set()
    return bool(common)


def _row_shared_fields(
    logical_recipient: _LogicalRecipient,
) -> tuple[RecipientFieldSet, ...]:
    return tuple(
        RecipientFieldSet(
            recipient_id=recipient.id,
            fields=dict(recipient.imported_fields or {}),
        )
        for recipient in logical_recipient.recipients
    )


def _recipient_row(
    *,
    logical_recipient: _LogicalRecipient,
    status: str,
    submissions: list[SubmissionForComparison],
    matches: list[_PairEvidence],
    candidate_submission_ids: set[uuid.UUID],
    duplicate_submission_ids: tuple[uuid.UUID, ...] = (),
) -> SubmissionMatchRow:
    source_recipients = logical_recipient.recipients
    broadcast_pairs = sorted(
        {(recipient.broadcast_id, recipient.broadcast_name) for recipient in source_recipients},
        key=lambda item: (item[1].casefold(), str(item[0])),
    )
    recipient_names = tuple(
        sorted(
            {
                name
                for recipient in source_recipients
                if (name := clean_whatsapp_name(recipient.name))
            },
            key=str.casefold,
        )
    )
    ordered_submissions = sorted(submissions, key=_submission_sort_key)
    all_evidence = tuple(
        sorted(
            (item for match in matches for item in match.evidence),
            key=lambda item: (
                str(item.submission_id),
                -item.weight,
                item.kind,
            ),
        )
    )
    basis = "+".join(sorted({item.kind for item in all_evidence})) or None
    timestamps = [
        *(recipient.updated_at for recipient in source_recipients),
        *(submission.updated_at for submission in ordered_submissions),
    ]
    # The matching profile intentionally omits unselected phone evidence for an
    # explicit policy. Row display and delivery diagnostics still need the
    # actual normalized roster destination without making it match evidence.
    normalized_phone = next(
        iter(
            sorted(
                {
                    phone
                    for recipient in source_recipients
                    if (phone := normalize_whatsapp_phone(recipient.phone))
                }
            )
        ),
        None,
    )
    confidence = (
        "high"
        if status in {"submitted", "multiple_submissions"}
        else "medium"
        if status == "needs_review"
        else "none"
    )
    return SubmissionMatchRow(
        duplicate_submission_ids=duplicate_submission_ids,
        status=status,
        match_basis=basis,
        normalized_phone=normalized_phone,
        recipient_ids=tuple(recipient.id for recipient in source_recipients),
        submission_ids=(
            tuple(submission.id for submission in ordered_submissions)
            if status in {"submitted", "multiple_submissions"}
            else ()
        ),
        broadcast_ids=tuple(item[0] for item in broadcast_pairs),
        broadcast_names=tuple(item[1] for item in broadcast_pairs),
        recipient_names=recipient_names,
        submission_names=tuple(submission.name for submission in ordered_submissions),
        updated_at=max(timestamps, key=_timestamp_key),
        confidence=confidence,
        match_evidence=all_evidence,
        candidate_submission_ids=tuple(sorted(candidate_submission_ids, key=str)),
        recipient_fields=_row_shared_fields(logical_recipient),
    )


def _unmatched_submission_row(
    submission: SubmissionForComparison,
    profile: _IdentityProfile,
) -> SubmissionMatchRow:
    return SubmissionMatchRow(
        status="unmatched_submission",
        match_basis=None,
        normalized_phone=next(iter(sorted(profile.phones)), None),
        recipient_ids=(),
        submission_ids=(submission.id,),
        broadcast_ids=(),
        broadcast_names=(),
        recipient_names=(),
        submission_names=(submission.name,),
        updated_at=submission.updated_at,
        confidence="none",
    )


def summarize_match_rows(
    rows: list[SubmissionMatchRow],
) -> SubmissionMatchSummary:
    """Summarize logical recipients and unassigned submission diagnostics."""

    recipient_rows = [row for row in rows if row.recipient_ids]
    matched_ids = {
        submission_id
        for row in recipient_rows
        if row.status in {"submitted", "multiple_submissions", "replacement"}
        for submission_id in row.submission_ids
    }
    needs_review_ids = {
        submission_id
        for row in recipient_rows
        if row.status == "needs_review"
        for submission_id in row.candidate_submission_ids
    }
    unmatched_ids = {
        submission_id
        for row in rows
        if row.status == "unmatched_submission"
        for submission_id in row.submission_ids
    }
    return SubmissionMatchSummary(
        total_recipients=len(recipient_rows),
        submitted_count=sum(
            row.status in {"submitted", "multiple_submissions", "replacement"}
            for row in recipient_rows
        ),
        not_submitted_count=sum(row.status == "not_submitted" for row in recipient_rows),
        multiple_submission_count=sum(
            row.status == "multiple_submissions" for row in recipient_rows
        ),
        matched_submission_count=len(matched_ids),
        needs_review_count=sum(row.status == "needs_review" for row in recipient_rows),
        needs_review_submission_count=len(needs_review_ids),
        unmatched_submission_count=len(unmatched_ids),
        replacement_count=sum(row.status == "replacement" for row in recipient_rows),
        rejected_upload_count=sum(row.status == "rejected_upload" for row in rows),
    )


def compare_group_submissions(
    recipients: list[RecipientForComparison],
    submissions: list[SubmissionForComparison],
) -> tuple[list[SubmissionMatchRow], SubmissionMatchSummary]:
    """Compare recipients and submissions with deterministic one-to-one ownership."""

    logical_recipients = _logical_recipients(recipients)
    ordered_submissions = sorted(submissions, key=_submission_sort_key)
    submission_profiles = [_submission_profile(submission) for submission in ordered_submissions]
    unique_names = _unique_compound_names(
        logical_recipients,
        submission_profiles,
    )
    unique_selected, roster_unique_selected = selected_field_value_uniqueness(
        (recipient.profile.selected_fields for recipient in logical_recipients),
        (profile.selected_fields for profile in submission_profiles),
    )
    evidence_indexes = _submission_evidence_indexes(submission_profiles)

    pairs: list[_PairEvidence] = []
    for recipient_index, recipient in enumerate(logical_recipients):
        candidate_indexes = _candidate_submission_indexes(
            recipient.profile,
            evidence_indexes,
        )
        for submission_index in sorted(candidate_indexes):
            submission = ordered_submissions[submission_index]
            profile = submission_profiles[submission_index]
            pair = _pair_evidence(
                recipient_index=recipient_index,
                recipient=recipient,
                submission_index=submission_index,
                submission=submission,
                submission_profile=profile,
                unique_compound_names=unique_names,
                unique_selected_values=unique_selected,
                roster_unique_selected_values=roster_unique_selected,
            )
            if pair:
                pairs.append(pair)

    pairs_by_recipient: dict[int, list[_PairEvidence]] = defaultdict(list)
    auto_pairs_by_submission: dict[int, list[_PairEvidence]] = defaultdict(list)
    for pair in pairs:
        pairs_by_recipient[pair.recipient_index].append(pair)
        if pair.auto_match:
            auto_pairs_by_submission[pair.submission_index].append(pair)

    assigned_pairs: dict[int, list[_PairEvidence]] = defaultdict(list)
    conflicted_pairs: dict[int, list[_PairEvidence]] = defaultdict(list)
    for submission_index, candidates in auto_pairs_by_submission.items():
        if len(candidates) == 1:
            assigned_pairs[candidates[0].recipient_index].append(candidates[0])
        else:
            # Any strong identity collision across logical recipients is
            # reviewable. Extra name evidence must never numerically override
            # a contradictory phone/email/passport/staff identifier.
            for candidate in candidates:
                conflicted_pairs[candidate.recipient_index].append(candidate)

    owned_submission_indexes = {
        pair.submission_index
        for recipient_pairs in assigned_pairs.values()
        for pair in recipient_pairs
    }
    rows: list[SubmissionMatchRow] = []
    assigned_submission_indexes: set[int] = set()
    candidate_submission_indexes: set[int] = set()
    for recipient_index, recipient in enumerate(logical_recipients):
        assigned = sorted(
            assigned_pairs.get(recipient_index, []),
            key=lambda pair: _submission_sort_key(ordered_submissions[pair.submission_index]),
        )
        potential = pairs_by_recipient.get(recipient_index, [])
        potential = [
            pair
            for pair in potential
            if (pair.submission_index not in owned_submission_indexes or pair in assigned)
        ]
        conflicts = conflicted_pairs.get(recipient_index, [])
        candidate_indexes = {
            pair.submission_index for pair in potential if not pair.auto_match or pair in conflicts
        }
        assigned_indexes = {pair.submission_index for pair in assigned}

        selected_party = any(
            item.kind in recipient.profile.selected_fields
            and (item.kind, item.recipient_value) in roster_unique_selected
            for pair in assigned for item in pair.evidence
        )
        unresolved_selected_candidates = any(
            pair.submission_index in candidate_indexes
            and any(
                item.kind in recipient.profile.selected_fields
                and item.kind not in {"name", "phone_number"}
                for item in pair.evidence
            )
            for pair in potential
        )
        contradictory_assignments = (
            len(assigned) > 1 and not selected_party and not _same_identity_basis(assigned)
        )
        duplicate_ids: tuple[uuid.UUID, ...] = ()
        if contradictory_assignments or (assigned and unresolved_selected_candidates):
            status = "needs_review"
            candidate_indexes.update(assigned_indexes)
            candidate_submission_indexes.update(assigned_indexes)
            candidate_submission_indexes.update(candidate_indexes)
            row_pairs = assigned + [pair for pair in potential if pair not in assigned]
            row_submissions = [ordered_submissions[index] for index in sorted(candidate_indexes)]
        elif assigned:
            assigned_submission_indexes.update(assigned_indexes)
            candidate_indexes = set()
            row_pairs = assigned
            row_submissions = [ordered_submissions[pair.submission_index] for pair in assigned]
            duplicate_ids = _duplicate_submission_ids(row_submissions)
            status = "multiple_submissions" if duplicate_ids else "submitted"
        elif potential:
            status = "needs_review"
            candidate_indexes.update(pair.submission_index for pair in potential)
            candidate_submission_indexes.update(candidate_indexes)
            row_pairs = potential
            row_submissions = [ordered_submissions[index] for index in sorted(candidate_indexes)]
        else:
            status = "not_submitted"
            row_pairs = []
            row_submissions = []

        rows.append(
            _recipient_row(
                logical_recipient=recipient,
                status=status,
                submissions=row_submissions,
                matches=row_pairs,
                candidate_submission_ids={
                    ordered_submissions[index].id for index in candidate_indexes
                },
                duplicate_submission_ids=duplicate_ids,
            )
        )

    for submission_index, (submission, profile) in enumerate(
        zip(ordered_submissions, submission_profiles, strict=True)
    ):
        if (
            submission_index not in assigned_submission_indexes
            and submission_index not in candidate_submission_indexes
        ):
            rows.append(_unmatched_submission_row(submission, profile))

    return rows, summarize_match_rows(rows)


def filter_and_sort_match_rows(
    rows: list[SubmissionMatchRow],
    *,
    status: str,
    sort_by: str,
    sort_order: str,
) -> list[SubmissionMatchRow]:
    filtered = rows if status == "all" else [row for row in rows if row.status == status]

    def name_key(row: SubmissionMatchRow) -> str | None:
        values = row.recipient_names or row.submission_names
        return values[0].casefold() if values else None

    def phone_key(row: SubmissionMatchRow) -> str | None:
        return row.normalized_phone

    def status_key(row: SubmissionMatchRow) -> str:
        return row.status

    def broadcast_key(row: SubmissionMatchRow) -> str | None:
        return row.broadcast_names[0].casefold() if row.broadcast_names else None

    key_functions: dict[
        str,
        Callable[[SubmissionMatchRow], str | datetime | None],
    ] = {
        "name": name_key,
        "phone": phone_key,
        "status": status_key,
        "broadcast": broadcast_key,
        "updated_at": lambda row: row.updated_at,
    }
    key_function = key_functions[sort_by]
    populated = [row for row in filtered if key_function(row) is not None]
    missing = [row for row in filtered if key_function(row) is None]
    populated.sort(
        key=lambda row: (
            key_function(row),
            str(row.recipient_ids),
            str(row.submission_ids),
        ),
        reverse=sort_order == "desc",
    )
    missing.sort(key=lambda row: (str(row.recipient_ids), str(row.submission_ids)))
    return populated + missing
