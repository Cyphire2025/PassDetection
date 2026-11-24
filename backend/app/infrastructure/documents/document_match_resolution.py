"""Focused match resolution policy; no parser or I/O side effects."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Mapping

from app.infrastructure.documents.document_identity_aliases import DocumentIdentityAliases
from app.infrastructure.documents.document_matcher_models import (
    ClassifiedDocument,
    DocumentMatchIndex,
    MatchResult,
    _IdentifierOwner,
)
from app.infrastructure.documents.document_matcher_rules import (
    _DOCUMENT_FILENAME_WORDS,
    _NAME_NOISE_TOKENS,
    MAX_FUZZY_CANDIDATES,
    MAX_NAME_TOKENS,
    MAX_PDF_TEXT_CHARS,
)


class DocumentMatchResolution(DocumentIdentityAliases):
    def _resolve_uuid_values(
        self,
        values: set[str],
        owners_by_value: Mapping[str, tuple[uuid.UUID, ...]],
        *,
        confidence: float,
        reason: str,
        ambiguity_reason: str,
    ) -> tuple[list[MatchResult], MatchResult | None]:
        matched_ids: set[uuid.UUID] = set()
        ambiguous = False
        for value in values:
            owners = owners_by_value.get(value, ())
            if len(owners) == 1:
                matched_ids.add(owners[0])
            elif len(owners) > 1:
                ambiguous = True
        matches = [
            MatchResult(passenger_id, confidence, "matched", reason)
            for passenger_id in sorted(matched_ids, key=str)
        ]
        if ambiguous:
            return matches, MatchResult(
                None,
                0.0,
                "needs_review",
                f"{ambiguity_reason}; manual review is required",
            )
        return matches, None

    def _resolve_name_windows(
        self,
        words: list[str],
        index: DocumentMatchIndex,
        *,
        confidence: float,
        reason: str,
        ambiguity_reason: str,
        exact_only: bool = False,
    ) -> tuple[list[MatchResult], MatchResult | None]:
        if not words:
            return [], None
        values: set[tuple[str, ...]] = set()
        lengths = index.name_lengths
        if exact_only:
            exact = tuple(words[:MAX_NAME_TOKENS])
            if exact in index.names:
                values.add(exact)
        else:
            for length in lengths:
                if length > len(words):
                    continue
                if length == 1 and len(words) != 1:
                    continue
                for start in range(0, len(words) - length + 1):
                    candidate = tuple(words[start : start + length])
                    if candidate in index.names:
                        values.add(candidate)

        compact_values: set[str] = set()
        if exact_only:
            compact = self._compact_name_value(words[:MAX_NAME_TOKENS])
            if compact in index.compact_names:
                compact_values.add(compact)
        else:
            # PDF generators and airline exports frequently remove the space
            # between given and middle names (for example
            # ``Akshaysunilkumar``), while filenames often put the surname
            # first. Resolve bounded compact windows against precomputed,
            # ambiguity-safe aliases so both filename and OCR text follow the
            # same deterministic identity policy.
            for start in range(len(words)):
                compact_parts: list[str] = []
                for width in range(1, MAX_NAME_TOKENS + 1):
                    end = start + width
                    if end > len(words):
                        break
                    compact_parts.append(words[end - 1])
                    compact = self._compact_name_value(compact_parts)
                    if len(compact) > 96:
                        break
                    if compact in index.compact_names:
                        compact_values.add(compact)

        matched_ids: set[uuid.UUID] = set()
        ambiguous = False
        for value in values:
            owners = index.names.get(value, ())
            if len(owners) == 1:
                matched_ids.add(owners[0])
            elif len(owners) > 1:
                ambiguous = True
        for compact_value in compact_values:
            owners = index.compact_names.get(compact_value, ())
            if len(owners) == 1:
                matched_ids.add(owners[0])
            elif len(owners) > 1:
                ambiguous = True
        matches = [
            MatchResult(passenger_id, confidence, "matched", reason)
            for passenger_id in sorted(matched_ids, key=str)
        ]
        if ambiguous:
            return matches, MatchResult(
                None,
                0.0,
                "needs_review",
                f"{ambiguity_reason}; manual review is required",
            )
        return matches, None

    def _resolve_ticket_manifest_partial_names(
        self,
        text: str,
        index: DocumentMatchIndex,
    ) -> list[MatchResult]:
        """Resolve shortened names only inside a ticket passenger manifest."""

        matched_ids: set[uuid.UUID] = set()
        for line in self._ticket_passenger_manifest_lines(text):
            words = [
                word
                for word in self._name_words(line)
                if word not in _NAME_NOISE_TOKENS
                and len(word) > 1
                and not any(character.isdigit() for character in word)
            ]
            # This fallback exists only for the common ``SURNAME, GIVEN`` row
            # where an airline omits the roster's middle name. Requiring one
            # comma and exactly two name tokens prevents flattened OCR/table
            # lines from combining adjacent passengers into a third identity.
            if line.count(",") != 1 or len(words) != 2:
                continue
            pair = tuple(sorted(words))
            owners = index.partial_name_pairs.get(pair, ())
            if len(owners) == 1:
                matched_ids.add(owners[0])
        return [
            MatchResult(
                passenger_id,
                0.88,
                "matched",
                "PDF passenger manifest uniquely matched a shortened passenger name",
            )
            for passenger_id in sorted(matched_ids, key=str)
        ]

    def _ticket_passenger_manifest_lines(self, text: str) -> tuple[str, ...]:
        lines = self._text_lines(text)
        manifest_lines: list[str] = []
        in_manifest = False
        for line in lines:
            normalized = self._normalize(line)
            is_manifest_heading = bool(
                re.search(r"\bpassenger(?:\s+s)?\s+information\b", normalized)
                or ("passenger" in normalized and "name" in normalized)
            )
            if not in_manifest:
                if is_manifest_heading:
                    in_manifest = True
                continue
            if re.search(
                r"\b(?:flight|fare|payment|contact)\s+information\b",
                normalized,
            ):
                break
            if is_manifest_heading or normalized in {"seat", "seats"}:
                continue
            manifest_lines.append(line)
            if len(manifest_lines) >= 1_000:
                break
        return tuple(manifest_lines)

    def _resolve_identifier_values(
        self,
        values: set[str],
        owners_by_value: Mapping[str, tuple[_IdentifierOwner, ...]],
        *,
        confidence: float,
        prefix: str,
    ) -> tuple[list[MatchResult], MatchResult | None]:
        unique_by_passenger: dict[uuid.UUID, _IdentifierOwner] = {}
        ambiguous_kinds: set[str] = set()
        for value in values:
            owners = owners_by_value.get(value, ())
            passenger_ids = {owner.passenger_id for owner in owners}
            if len(passenger_ids) == 1 and owners:
                owner = owners[0]
                unique_by_passenger.setdefault(owner.passenger_id, owner)
            elif len(passenger_ids) > 1:
                ambiguous_kinds.update(owner.kind for owner in owners)

        matches = [
            MatchResult(
                passenger_id,
                confidence,
                "matched",
                f"{prefix} {owner.kind} uniquely matched from {owner.source}",
            )
            for passenger_id, owner in sorted(
                unique_by_passenger.items(),
                key=lambda item: str(item[0]),
            )
        ]
        if ambiguous_kinds:
            kinds = ", ".join(sorted(ambiguous_kinds))
            return matches, MatchResult(
                None,
                0.0,
                "needs_review",
                f"{prefix} {kinds} matches multiple passengers; manual review is required",
            )
        return matches, None

    def _bounded_fuzzy_name_match(
        self,
        words: list[str],
        index: DocumentMatchIndex,
    ) -> MatchResult | None:
        document_tokens = {
            token for token in words if len(token) > 1 and token not in _NAME_NOISE_TOKENS
        }
        if not document_tokens:
            return None

        hit_counts: dict[uuid.UUID, int] = defaultdict(int)
        for token in document_tokens:
            owners = index.name_token_passengers.get(token, ())
            # Extremely common name tokens add CPU but no useful discrimination.
            if len(owners) > 64:
                continue
            for passenger_id in owners:
                hit_counts[passenger_id] += 1
        if not hit_counts:
            return None

        candidate_ids = sorted(hit_counts, key=lambda item: (-hit_counts[item], str(item)))[
            :MAX_FUZZY_CANDIDATES
        ]
        scores: list[tuple[float, uuid.UUID]] = []
        for passenger_id in candidate_ids:
            profile = index.profiles_by_id[passenger_id]
            best = 0.0
            for name in profile.names:
                meaningful = {
                    token for token in name if len(token) > 1 and token not in _NAME_NOISE_TOKENS
                }
                if len(meaningful) < 2:
                    continue
                coverage = len(meaningful & document_tokens) / len(meaningful)
                best = max(best, coverage * 0.86)
            if best:
                scores.append((best, passenger_id))
        if not scores:
            return None
        scores.sort(key=lambda item: (-item[0], str(item[1])))
        best_score, best_id = scores[0]
        second_score = scores[1][0] if len(scores) > 1 else 0.0
        if best_score >= 0.82 and best_score - second_score >= 0.15:
            return MatchResult(
                best_id,
                best_score,
                "matched",
                "PDF text passenger-name tokens uniquely matched",
            )
        if best_score >= 0.62:
            return MatchResult(
                None,
                best_score,
                "needs_review",
                "Passenger-name evidence is incomplete or ambiguous; manual review is required",
            )
        return None

    def _filename_identifier_values(self, filename_stem: str) -> set[str]:
        tokens = [token.upper() for token in re.findall(r"[A-Za-z0-9]+", filename_stem)]
        values: set[str] = set()
        for index, token in enumerate(tokens[:24]):
            if any(character.isdigit() for character in token):
                values.add(token)
            for width in (2, 3):
                parts = tokens[index : index + width]
                if len(parts) != width:
                    continue
                joined = "".join(parts)
                if len(joined) <= 64 and any(character.isdigit() for character in joined):
                    values.add(joined)
        meaningful = [token for token in tokens if token.casefold() not in _DOCUMENT_FILENAME_WORDS]
        compact = "".join(meaningful)
        if compact and len(compact) <= 64 and any(character.isdigit() for character in compact):
            values.add(compact)
        return {
            value
            for value in values
            if 1 <= len(value) <= 64 and (not value.isdigit() or len(value) >= 3)
        }

    def _content_passport_values(self, document: ClassifiedDocument) -> set[str]:
        values: set[str] = set()
        if document.extracted_passport_number:
            values.add(self._normalize_identifier(document.extracted_passport_number) or "")
        for match in re.finditer(
            r"\b[A-Z]{1,2}[\s-]?[0-9]{6,8}\b",
            document.text.upper(),
        ):
            if value := self._normalize_identifier(match.group(0)):
                values.add(value)
        for match in re.finditer(
            r"\b(?:PASSPORT|TRAVEL\s+DOCUMENT)(?:\s+(?:NO|NUM|NUMBER))?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\s-]{2,20})",
            document.text.upper(),
        ):
            candidate = match.group(1).split()[0]
            if value := self._normalize_identifier(candidate):
                values.add(value)
        values.discard("")
        return values

    def _content_labeled_identifier_values(self, text: str) -> set[str]:
        values: set[str] = set()
        pattern = re.compile(
            r"\b(?:STAFF|EMPLOYEE|AGENT|PERSONNEL)(?:\s+(?:CODE|ID|NO|NUMBER))"
            r"\s*[:#\-]?\s*([A-Z0-9][A-Z0-9_-]{0,63})\b",
            flags=re.IGNORECASE,
        )
        for match in pattern.finditer(text[:MAX_PDF_TEXT_CHARS]):
            if value := self._normalize_identifier(match.group(1)):
                values.add(value)
        return values
