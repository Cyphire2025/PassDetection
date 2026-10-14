"""Conservative exact operational matching; never document-access proof.

Exact names need two other types. Compatible partial names need an exact passport
and two further types. Known passport/birth conflicts veto either association.
Normalization is O(F + L) time/space for at most 128 fields and 512 characters
per value; it does not reorder names, remove accents or correct OCR characters.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.exceptions.exceptions import ValidationError
from app.domain.services.identity_decisions import IdentityDecision as IdentityDecision
from app.domain.services.identity_decisions import compare_identity as compare_identity
from app.domain.services.traveller_verification import exact_passport_number
from app.domain.value_objects.passport_fields import normalize_passport_date
from app.domain.value_objects.phone_number import normalize_phone_number

_EXCEL_MIDNIGHT_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]00:00:00(?:\.0{1,6})?$")
_ALIASES = {
    "name": ("name", "full_name", "passenger_name", "traveller_name", "client_name"),
    "passport": ("passport", "passport_no", "passport_number", "passport_num"),
    "birth_date": ("dob", "date_of_birth", "birth_date", "birthdate"),
    "phone": ("phone", "phone_number", "mobile", "mobile_number", "whatsapp_number", "client_phone"),
    "email": ("email", "email_address", "client_email"),
    "code": ("agent_code", "producer_code", "staff_code", "employee_code", "individual_code"),
}


def normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def normalize_individual_code(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def _value(kind: str, value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    if kind == "name":
        return normalize_name(value)
    if kind == "passport":
        return exact_passport_number(value)
    if kind == "birth_date":
        # Excel date cells round-trip as naive midnight datetimes. Preserve the
        # exact calendar date; do not infer locale, timezone or numeric serials.
        midnight = _EXCEL_MIDNIGHT_DATE.fullmatch(value)
        if midnight is not None:
            value = midnight.group(1)
        return normalize_passport_date(value, field="date_of_birth")
    if kind == "phone":
        return normalize_phone_number(value) or ""
    if kind == "email":
        local, separator, domain = value.rpartition("@")
        if not separator or not local or not domain or any(char.isspace() for char in value):
            return ""
        # Preserve local-part case: arbitrary mailbox case folding can merge
        # distinct mailboxes. DNS domain case is immaterial.
        return f"{local}@{domain.casefold()}"
    return normalize_individual_code(value)  # Preserve case and leading zeroes.


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    values: tuple[tuple[str, str], ...]
    conflicts: frozenset[str] = frozenset()

    def get(self, kind: str) -> frozenset[str]:
        return frozenset(value for field, value in self.values if field == kind)


def identity_evidence(fields: Mapping[str, object], *, name: str | None = None,
    phone: str | None = None, email: str | None = None, authoritative_name: str | None = None,
) -> IdentityEvidence:
    """Reject contradictory aliases rather than silently choosing one column."""
    if len(fields) > 128:
        return IdentityEvidence((), frozenset({"input_limit"}))
    raw = _raw_identity_fields(fields, name, phone, email, authoritative_name)
    values: list[tuple[str, str]] = []
    conflicts: set[str] = set()
    for kind, aliases in _ALIASES.items():
        normalized: set[str] = set()
        for alias in aliases:
            for value in raw.get(alias, []):
                try:
                    result = _value(kind, value) if len(value) <= 512 else ""
                except (ValueError, ValidationError):
                    result = ""
                if result:
                    normalized.add(f"{alias}:{result}" if kind == "code" else result)
                else:
                    conflicts.add(kind)
        if kind != "code" and len(normalized) > 1:
            conflicts.add(kind)
        values.extend((kind, value) for value in sorted(normalized))
    return IdentityEvidence(tuple(values), frozenset(conflicts))


def _raw_identity_fields(fields: Mapping[str, object], name: str | None, phone: str | None,
    email: str | None, authoritative_name: str | None,
) -> dict[str, list[str]]:
    raw: dict[str, list[str]] = {}
    for key, value in fields.items():
        if isinstance(value, str) and value.strip():
            raw.setdefault(_key(key), []).append(value)
    # Submitted values supplement imports. Only a separately accepted passport
    # name may replace display-name aliases; all other contradictions survive.
    for key, value in (("name", name), ("phone", phone), ("email", email)):
        if value:
            raw.setdefault(key, []).append(value)
    if authoritative_name:
        raw = {key: values for key, values in raw.items() if key not in _ALIASES["name"]}
        raw["name"] = [authoritative_name]
    if not any(alias in raw for alias in _ALIASES["name"]):
        given = raw.get("given_names", [])
        surname = raw.get("surname", [])
        if len(given) <= 1 and len(surname) <= 1 and (given or surname):
            raw["name"] = [" ".join([*given, *surname])]
    return raw
