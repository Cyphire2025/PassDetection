"""Conservative, evidence-first email association policy."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
    DocumentMatcher,
    MatchResult,
)


@dataclass(frozen=True)
class GroupAssociation:
    group_id: uuid.UUID | None
    confidence: float
    status: str
    evidence: tuple[str, ...]
    candidate_group_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class PassengerAssociation:
    passenger_id: uuid.UUID | None
    confidence: float
    status: str
    evidence: tuple[str, ...]
    candidate_passenger_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class GroupForAssociation:
    id: uuid.UUID
    name: str
    token: str
    destination: str | None
    travel_date: date | None


def associate_group(
    *,
    email_text: str,
    document: ClassifiedDocument,
    groups: list[GroupForAssociation],
    passengers: list[PassportSubmission],
) -> GroupAssociation:
    """Choose a group only when deterministic evidence is unique.

    Exact passport numbers are authoritative. Group text requires an exact
    group name plus a corroborating destination or travel date. Fuzzy names
    alone are deliberately never an automatic group decision.
    """

    normalized_text = _normalize(f"{email_text} {document.original_filename} {document.text}")
    passengers_by_group: dict[uuid.UUID, list[PassportSubmission]] = {}
    for passenger in passengers:
        passengers_by_group.setdefault(passenger.group_id, []).append(passenger)

    passport_number = _normalize(document.extracted_passport_number or "")
    if passport_number:
        exact_passengers = [
            passenger
            for passenger in passengers
            if _passenger_passport_number(passenger) == passport_number
        ]
        exact_group_ids = tuple(dict.fromkeys(passenger.group_id for passenger in exact_passengers))
        if len(exact_passengers) == 1 and len(exact_group_ids) == 1:
            return GroupAssociation(
                group_id=exact_group_ids[0],
                confidence=0.99,
                status="matched",
                evidence=("passport_number_exact",),
                candidate_group_ids=exact_group_ids,
            )
        if exact_group_ids:
            return GroupAssociation(
                group_id=None,
                confidence=0.98,
                status="needs_review",
                evidence=("passport_number_conflict",),
                candidate_group_ids=exact_group_ids,
            )

    scored: list[tuple[float, GroupForAssociation, tuple[str, ...]]] = []
    for group in groups:
        score = 0.0
        evidence: list[str] = []
        normalized_group_name = _normalize(group.name)
        exact_group_name = bool(
            normalized_group_name
            and len(normalized_group_name) >= 4
            and _contains_phrase(normalized_text, normalized_group_name)
        )
        if exact_group_name:
            score += 0.72
            evidence.append("group_name_exact")

        corroboration_text = (
            normalized_text.replace(normalized_group_name, " ", 1)
            if exact_group_name
            else normalized_text
        )
        normalized_destination = _normalize(group.destination or "")
        if (
            exact_group_name
            and normalized_destination
            and len(normalized_destination) >= 3
            and _contains_phrase(corroboration_text, normalized_destination)
        ):
            score += 0.14
            evidence.append("destination_exact")

        if (
            exact_group_name
            and group.travel_date
            and _date_appears(
                normalized_text,
                group.travel_date,
            )
        ):
            score += 0.14
            evidence.append("travel_date_exact")

        # Upload tokens are high-entropy identifiers, but never include the
        # token itself in evidence or logs.
        if group.token and group.token in email_text:
            score = 1.0
            evidence = ["group_upload_token_exact"]

        if score:
            scored.append((min(score, 1.0), group, tuple(evidence)))

    if not scored:
        # Preserve candidate groups suggested by strong document-name matches
        # for human review without converting the fuzzy result into automation.
        matcher = DocumentMatcher()
        fuzzy_candidates: list[tuple[float, uuid.UUID]] = []
        for group in groups:
            match = matcher.match(document, passengers_by_group.get(group.id, []))
            if match.passenger_id and match.confidence >= 0.82:
                fuzzy_candidates.append((match.confidence, group.id))
        fuzzy_candidates.sort(key=lambda item: (-item[0], str(item[1])))
        return GroupAssociation(
            group_id=None,
            confidence=fuzzy_candidates[0][0] if fuzzy_candidates else 0.0,
            status="needs_review",
            evidence=("passenger_name_candidate",) if fuzzy_candidates else (),
            candidate_group_ids=tuple(group_id for _, group_id in fuzzy_candidates[:5]),
        )

    scored.sort(key=lambda item: (-item[0], str(item[1].id)))
    best_score, best_group, best_evidence = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    candidates = tuple(group.id for _, group, _ in scored[:5])
    if best_score >= 0.85 and best_score - runner_up >= 0.15:
        return GroupAssociation(
            group_id=best_group.id,
            confidence=best_score,
            status="matched",
            evidence=best_evidence,
            candidate_group_ids=candidates,
        )
    return GroupAssociation(
        group_id=best_group.id,
        confidence=best_score,
        status="needs_review",
        evidence=best_evidence,
        candidate_group_ids=candidates,
    )


def associate_passenger(
    *,
    document: ClassifiedDocument,
    passengers: list[PassportSubmission],
) -> PassengerAssociation:
    """Return a passenger proposal; only exact passport evidence auto-matches."""

    matches = DocumentMatcher().match_all(document, passengers)
    real_matches = [match for match in matches if match.passenger_id is not None]
    if not real_matches:
        return PassengerAssociation(
            passenger_id=None,
            confidence=0.0,
            status="needs_review",
            evidence=(),
        )

    exact = [
        match
        for match in real_matches
        if match.confidence >= 0.98 and "Passport number" in match.reason
    ]
    if len(exact) == 1:
        exact_passenger_id = exact[0].passenger_id
        if exact_passenger_id is None:  # Defensive; real_matches excludes this.
            raise AssertionError("Exact passenger match is missing its identifier")
        return PassengerAssociation(
            passenger_id=exact_passenger_id,
            confidence=exact[0].confidence,
            status="matched",
            evidence=("passport_number_exact",),
            candidate_passenger_ids=(exact_passenger_id,),
        )

    ordered: list[MatchResult] = sorted(
        real_matches,
        key=lambda match: (-match.confidence, str(match.passenger_id)),
    )
    best = ordered[0]
    return PassengerAssociation(
        passenger_id=best.passenger_id,
        confidence=best.confidence,
        status="needs_review",
        evidence=("passenger_name_candidate",),
        candidate_passenger_ids=tuple(
            match.passenger_id for match in ordered[:5] if match.passenger_id is not None
        ),
    )


def _passenger_passport_number(passenger: PassportSubmission) -> str:
    fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    return _normalize(str(fields.get("passport_number") or ""))


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _contains_phrase(haystack: str, needle: str) -> bool:
    return f" {needle} " in f" {haystack} "


def _date_appears(normalized_text: str, value: date) -> bool:
    variants = {
        value.isoformat(),
        value.strftime("%d %m %Y"),
        value.strftime("%d %b %Y").casefold(),
        value.strftime("%d %B %Y").casefold(),
        value.strftime("%d %m %y"),
    }
    return any(_normalize(variant) in normalized_text for variant in variants)
