"""Choose coherent passenger results and stable duplicate winners from evidence."""

from __future__ import annotations

import uuid

from app.infrastructure.documents.document_matcher_models import MatchResult


def select_single_passenger_match(matches: list[MatchResult]) -> MatchResult:
    automatic = [match for match in matches if match.status == "matched"]
    if len(automatic) == 1:
        return automatic[0]
    if len(automatic) > 1:
        return MatchResult(
            None,
            max(match.confidence for match in automatic),
            "needs_review",
            "Multiple passengers were identified; manual review is required",
        )
    return (
        matches[0]
        if matches
        else MatchResult(
            None,
            0.0,
            "needs_review",
            "No passenger match found",
        )
    )


def resolve_content_evidence(
    *, content_match_groups: list[list[MatchResult]], content_ambiguities: list[MatchResult]
) -> list[MatchResult] | None:
    if content_ambiguities:
        return [
            MatchResult(
                None,
                0.0,
                "needs_review",
                "PDF identity evidence is ambiguous; manual review is required",
            )
        ]
    if content_match_groups:
        matches_by_passenger: dict[uuid.UUID, MatchResult] = {}
        evidence_sets: list[set[uuid.UUID]] = []
        for matches in content_match_groups:
            evidence_set = {
                match.passenger_id for match in matches if match.passenger_id is not None
            }
            if evidence_set:
                evidence_sets.append(evidence_set)
            for match in matches:
                if match.passenger_id is None:
                    continue
                current = matches_by_passenger.get(match.passenger_id)
                if current is None or match.confidence > current.confidence:
                    matches_by_passenger[match.passenger_id] = match

        if len(matches_by_passenger) == 1:
            return list(matches_by_passenger.values())

        # The first evidence category must identify one coherent passenger set.
        # Later categories may narrow that set but must never expand it. This
        # rejects overlapping contradictions such as {A, B} versus {B, C}, or
        # extra names attached to an authoritative passport match. Collection
        # order is passport, full-text names, extracted name, then identifiers.
        dominant_evidence_set = evidence_sets[0] if len(evidence_sets[0]) > 1 else None
        evidence_is_consistent = dominant_evidence_set is not None and all(
            evidence_set.issubset(dominant_evidence_set) for evidence_set in evidence_sets
        )
        if evidence_is_consistent:
            assert dominant_evidence_set is not None
            return [
                MatchResult(
                    passenger_id,
                    matches_by_passenger[passenger_id].confidence,
                    "matched",
                    "PDF contains multiple uniquely identified passengers",
                )
                for passenger_id in sorted(dominant_evidence_set, key=str)
            ]
        return [
            MatchResult(
                None,
                0.0,
                "needs_review",
                "PDF identity evidence points to different passengers; manual review is required",
            )
        ]
    return None


def mark_duplicate_matches(matches: list[MatchResult]) -> list[MatchResult]:
    best_by_passenger: dict[uuid.UUID, int] = {}
    for index, match in enumerate(matches):
        if not match.passenger_id:
            continue
        best_index = best_by_passenger.get(match.passenger_id)
        if best_index is None or match.confidence > matches[best_index].confidence:
            best_by_passenger[match.passenger_id] = index

    deduped: list[MatchResult] = []
    for index, match in enumerate(matches):
        if match.passenger_id and best_by_passenger.get(match.passenger_id) != index:
            deduped.append(
                MatchResult(
                    match.passenger_id,
                    match.confidence,
                    "duplicate_document",
                    "Another uploaded file matched this passenger better",
                )
            )
        else:
            deduped.append(match)
    return deduped
