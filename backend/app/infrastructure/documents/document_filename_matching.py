"""Resolve filename identity evidence before any PDF-content evidence."""

from __future__ import annotations

from app.infrastructure.documents.document_match_resolution import DocumentMatchResolution
from app.infrastructure.documents.document_matcher_models import DocumentMatchIndex, MatchResult


def match_filename_evidence(
    *, filename: str, prepared: DocumentMatchIndex, resolver: DocumentMatchResolution
) -> list[MatchResult] | None:
    """None permits content matching; a review result terminates ambiguous evidence."""

    filename_identifier_values = resolver._filename_identifier_values(filename)
    passport_matches, ambiguity = resolver._resolve_uuid_values(
        filename_identifier_values,
        prepared.passports,
        confidence=0.995,
        reason="Filename Passport number uniquely matched",
        ambiguity_reason="Filename passport number matches multiple passengers",
    )
    filename_ambiguities = [ambiguity] if ambiguity is not None else []

    filename_words = resolver._name_words(filename)
    filename_name_matches, ambiguity = resolver._resolve_name_windows(
        filename_words,
        prepared,
        confidence=0.97,
        reason="Filename exact passenger name uniquely matched",
        ambiguity_reason="Filename passenger name matches multiple passengers",
    )
    if ambiguity is not None:
        filename_ambiguities.append(ambiguity)

    filename_identifier_matches, ambiguity = resolver._resolve_identifier_values(
        filename_identifier_values,
        prepared.identifiers,
        confidence=0.93,
        prefix="Filename",
    )
    if ambiguity is not None:
        filename_ambiguities.append(ambiguity)

    filename_match_groups = [
        matches
        for matches in (
            passport_matches,
            filename_name_matches,
            filename_identifier_matches,
        )
        if matches
    ]
    filename_id_sets = [
        {match.passenger_id for match in matches if match.passenger_id}
        for matches in filename_match_groups
    ]
    if filename_ambiguities or (
        len(filename_id_sets) > 1
        and any(candidate != filename_id_sets[0] for candidate in filename_id_sets[1:])
    ):
        return [
            MatchResult(
                None,
                0.0,
                "needs_review",
                "Filename evidence is ambiguous or contradictory; manual review is required",
            )
        ]
    if filename_match_groups:
        # The category order encodes the public precedence: passport,
        # exact name, then stored staff/agent/custom identifier.
        return filename_match_groups[0]
    return None
