"""Focused identity aliases policy; no parser or I/O side effects."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from app.domain.entities.entities import PassportSubmission
from app.domain.value_objects.personnel_codes import (
    prefixed_agent_employee_code,
    prefixed_staff_code,
)
from app.infrastructure.documents.document_identity_limits import DocumentIdentityLimits
from app.infrastructure.documents.document_matcher_rules import (
    _AGENT_CODE_KEYS,
    _FULL_NAME_KEYS,
    _GIVEN_NAME_KEYS,
    _IDENTIFIER_KEY_EXCLUSIONS,
    _IDENTIFIER_KEY_TOKENS,
    _NAME_NOISE_TOKENS,
    _STAFF_CODE_KEYS,
    _SURNAME_KEYS,
    MAX_NAME_TOKENS,
    MAX_PASSENGER_IDENTIFIERS,
    MAX_PASSENGER_NAMES,
    MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS,
    MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER,
    MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST,
)
from app.infrastructure.documents.document_text_normalization import DocumentTextNormalization


class DocumentIdentityAliases(DocumentTextNormalization):
    def _passport_fields(self, passenger: PassportSubmission) -> dict[str, Any]:
        fields = dict(passenger.extracted_fields or {})
        fields.update(passenger.confirmed_fields or {})
        return fields

    def _normalized_passenger_names(
        self,
        passenger: PassportSubmission,
        fields: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], ...]:
        candidates: list[Any] = [getattr(passenger, "display_name", None), passenger.client_name]
        candidates.extend(self._mapping_values(fields, _FULL_NAME_KEYS))
        given_values = self._mapping_values(fields, _GIVEN_NAME_KEYS) or [""]
        surname_values = self._mapping_values(fields, _SURNAME_KEYS) or [""]
        for given in given_values:
            for surname in surname_values:
                given_text = str(given or "").strip()
                surname_text = str(surname or "").strip()
                candidates.extend(
                    [
                        " ".join(part for part in (given_text, surname_text) if part),
                        " ".join(part for part in (surname_text, given_text) if part),
                    ]
                )

        names: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()
        for candidate in candidates:
            tokens = tuple(self._name_words(str(candidate or ""))[:MAX_NAME_TOKENS])
            if not tokens or tokens in seen:
                continue
            seen.add(tokens)
            names.append(tokens)
            if len(names) >= MAX_PASSENGER_NAMES:
                break
        return tuple(names)

    def _identifier_aliases(self, mapping: Mapping[str, Any]) -> list[tuple[str, str]]:
        limits = self._identity_limits()
        aliases: list[tuple[str, str]] = []
        normalized_mapping = {self._normalize_key(key): value for key, value in mapping.items()}
        person_type = normalized_mapping.get("agent_employee_type")
        for raw_key, raw_value in list(mapping.items())[:limits.passenger_identifiers]:
            key = self._normalize_key(raw_key)
            if not self._is_identifier_key(key):
                continue
            value = self._normalize_identifier(raw_value)
            if not value or not any(character.isdigit() for character in value):
                continue
            kind = self._identifier_kind(key)
            aliases.append((value, kind))
            if key in _STAFF_CODE_KEYS:
                if prefixed := prefixed_staff_code(raw_value):
                    if normalized_prefixed := self._normalize_identifier(prefixed):
                        aliases.append((normalized_prefixed, "staff code"))
            if key in _AGENT_CODE_KEYS:
                prefixed = prefixed_agent_employee_code(person_type, raw_value)
                if prefixed and (normalized_prefixed := self._normalize_identifier(prefixed)):
                    aliases.append((normalized_prefixed, "agent or employee code"))
        return list(dict.fromkeys(aliases))[:limits.passenger_identifiers]

    def _mapping_values(
        self,
        mapping: Mapping[str, Any],
        keys: frozenset[str],
    ) -> list[Any]:
        values: list[Any] = []
        for raw_key, value in mapping.items():
            normalized = self._normalize_key(raw_key)
            base_key = re.sub(r"_\d+$", "", normalized)
            if normalized in keys or base_key in keys:
                values.append(value)
        return values

    def _compact_name_aliases(self, name: tuple[str, ...]) -> set[str]:
        """Return bounded joined-name aliases without weakening uniqueness checks."""

        tokens = tuple(
            token
            for token in name[:MAX_NAME_TOKENS]
            if token not in _NAME_NOISE_TOKENS and len(token) > 1
        )
        if not tokens:
            return set()

        aliases: set[str] = set()
        # Rotations cover the common given-middle-surname versus
        # surname-given-middle layouts. Reversed rotations cover airline/name
        # exports that reverse the complete sequence. This stays linear in the
        # number of name tokens instead of creating an unbounded permutation
        # index for large rosters.
        for ordered in (tokens, tuple(reversed(tokens))):
            for offset in range(len(ordered)):
                rotated = ordered[offset:] + ordered[:offset]
                compact = self._compact_name_value(rotated)
                if 8 <= len(compact) <= 96:
                    aliases.add(compact)
        return aliases

    def _partial_name_pair_aliases(self, name: tuple[str, ...]) -> set[tuple[str, ...]]:
        """Index unique two-token fallbacks for shortened airline manifests.

        Airlines often omit a middle name from the compact passenger list even
        though the operations roster keeps the complete passport name. Exact
        and compact full-name matching remain authoritative. These pairs are
        used only inside an explicitly labelled passenger-information section,
        and a pair is eligible only when it belongs to one scoped passenger.
        """

        tokens = tuple(
            dict.fromkeys(
                token
                for token in name[:MAX_NAME_TOKENS]
                if token not in _NAME_NOISE_TOKENS
                and len(token) > 1
                and not any(character.isdigit() for character in token)
            )
        )
        if len(tokens) < 3:
            return set()
        return {
            tuple(sorted((tokens[left], tokens[right])))
            for left in range(len(tokens) - 1)
            for right in range(left + 1, len(tokens))
            if len(tokens[left]) + len(tokens[right]) >= 7
        }

    def _compact_name_value(self, tokens: Iterable[str]) -> str:
        # Callers pass tokens produced by `_name_words`, so they are already
        # normalized and contain no separators. Avoid regex work in the bounded
        # full-document sliding window.
        return "".join(token for token in tokens if token)

    def _is_identifier_key(self, key: str) -> bool:
        if not key or key in _IDENTIFIER_KEY_EXCLUSIONS or key.startswith("source_"):
            return False
        if key in _STAFF_CODE_KEYS or key in _AGENT_CODE_KEYS:
            return True
        tokens = set(key.split("_"))
        return bool(tokens & _IDENTIFIER_KEY_TOKENS)

    def _identifier_kind(self, key: str) -> str:
        if key in _AGENT_CODE_KEYS or "agent" in key:
            return "agent or employee code"
        if key in _STAFF_CODE_KEYS or "staff" in key or "employee" in key:
            return "staff code"
        return "stored identifier"

    def _safe_identifier_kind(self, value: str) -> str:
        normalized = self._normalize_key(value).replace("_", " ")
        return normalized[:40] if normalized else "stored identifier"

    def _safe_identifier_source(self, value: str) -> str:
        normalized = " ".join(re.findall(r"[A-Za-z0-9]+", str(value)))
        return normalized[:40] if normalized else "linked group data"

    def _freeze_uuid_index(
        self,
        index: Mapping[str, set[uuid.UUID]],
    ) -> dict[str, tuple[uuid.UUID, ...]]:
        return {value: tuple(sorted(owners, key=str)) for value, owners in index.items()}

    def _freeze_name_index(
        self,
        index: Mapping[tuple[str, ...], set[uuid.UUID]],
    ) -> dict[tuple[str, ...], tuple[uuid.UUID, ...]]:
        return {value: tuple(sorted(owners, key=str)) for value, owners in index.items()}

    def _identity_limits(self) -> DocumentIdentityLimits:
        return DocumentIdentityLimits(
            MAX_PASSENGER_IDENTIFIERS,
            MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER,
            MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST,
            MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS,
        )
