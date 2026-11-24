"""Collect ordered PDF identity evidence through the existing resolution policy."""

from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.documents.document_match_resolution import DocumentMatchResolution
from app.infrastructure.documents.document_matcher_models import (
    ClassifiedDocument,
    DocumentMatchIndex,
    MatchResult,
)


@dataclass(frozen=True, slots=True)
class ContentMatchEvidence:
    """One request's owned evidence lists, tokens and pending full-name resolution."""

    match_groups: list[list[MatchResult]]
    ambiguities: list[MatchResult]
    words: list[str]
    name_result: tuple[list[MatchResult], MatchResult | None]


def collect_primary_content_evidence(
    *, document: ClassifiedDocument, prepared: DocumentMatchIndex,
    resolver: DocumentMatchResolution,
) -> ContentMatchEvidence:
    content_match_groups: list[list[MatchResult]] = []
    content_ambiguities: list[MatchResult] = []
    content_passport_values = resolver._content_passport_values(document)
    passport_matches, ambiguity = resolver._resolve_uuid_values(
        content_passport_values,
        prepared.passports,
        confidence=0.98,
        reason="PDF text Passport number uniquely matched",
        ambiguity_reason="PDF text passport number matches multiple passengers",
    )
    if ambiguity is not None:
        content_ambiguities.append(ambiguity)
    if passport_matches:
        content_match_groups.append(passport_matches)

    content_words = resolver._name_words(document.text)
    # Resolve the complete text before the convenience `extracted_name`
    # field. Combined airline bookings commonly expose the first traveller
    # as a header value while listing every passenger later in the same PDF.
    # The complete exact-name set is therefore the authoritative name set;
    # the first-name extraction may safely narrow it but must not hide the
    # remaining passengers.
    name_matches, ambiguity = resolver._resolve_name_windows(
        content_words,
        prepared,
        confidence=0.94,
        reason="PDF text exact passenger name uniquely matched",
        ambiguity_reason="PDF text passenger name matches multiple passengers",
    )
    return ContentMatchEvidence(
        content_match_groups, content_ambiguities, content_words, (name_matches, ambiguity)
    )


def merge_manifest_name_matches(
    name_matches: list[MatchResult], partial_name_matches: list[MatchResult]
) -> list[MatchResult]:
    matches_by_id = {
        match.passenger_id: match
        for match in name_matches
        if match.passenger_id is not None
    }
    for match in partial_name_matches:
        if match.passenger_id is not None:
            matches_by_id.setdefault(match.passenger_id, match)
    name_matches = [
        matches_by_id[passenger_id] for passenger_id in sorted(matches_by_id, key=str)
    ]
    return name_matches


def collect_secondary_content_evidence(
    *, document: ClassifiedDocument, prepared: DocumentMatchIndex,
    resolver: DocumentMatchResolution, evidence: ContentMatchEvidence,
    name_matches: list[MatchResult], ambiguity: MatchResult | None,
) -> None:
    content_match_groups = evidence.match_groups
    content_ambiguities = evidence.ambiguities
    if ambiguity is not None:
        content_ambiguities.append(ambiguity)
    if name_matches:
        content_match_groups.append(name_matches)

    extracted_name_words = resolver._name_words(document.extracted_name or "")
    if extracted_name_words:
        name_matches, ambiguity = resolver._resolve_name_windows(
            extracted_name_words,
            prepared,
            confidence=0.96,
            reason="Extracted passenger name uniquely matched",
            ambiguity_reason="Extracted passenger name matches multiple passengers",
            exact_only=True,
        )
        if ambiguity is not None:
            content_ambiguities.append(ambiguity)
        if name_matches:
            content_match_groups.append(name_matches)

    content_identifier_values = resolver._content_labeled_identifier_values(document.text)
    identifier_matches, ambiguity = resolver._resolve_identifier_values(
        content_identifier_values,
        prepared.identifiers,
        confidence=0.89,
        prefix="PDF text",
    )
    if ambiguity is not None:
        content_ambiguities.append(ambiguity)
    if identifier_matches:
        content_match_groups.append(identifier_matches)
