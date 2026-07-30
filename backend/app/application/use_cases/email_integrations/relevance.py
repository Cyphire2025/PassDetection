"""Deterministic email relevance classification.

Incoming text is data, never an instruction source. This policy does not call
an AI model or expose tools, which keeps prompt injection out of the first
provider slice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TRAVEL_TERMS = frozenset(
    {
        "airline",
        "boarding",
        "booking",
        "departure",
        "e ticket",
        "evisa",
        "flight",
        "immigration",
        "itinerary",
        "passport",
        "pnr",
        "ticket",
        "travel",
        "visa",
    }
)

STRONG_GROUP_EVIDENCE = frozenset(
    {
        "passport_number_exact",
        "group_upload_token_exact",
        "group_name_exact",
        "passenger_email_exact",
        "passenger_phone_exact",
    }
)

GROUP_CONTEXT_EVIDENCE = STRONG_GROUP_EVIDENCE | {
    "passenger_name_exact",
    "destination_exact",
    "travel_date_exact",
    "conflicting_roster_identifiers",
}


@dataclass(frozen=True)
class RelevanceDecision:
    status: str
    confidence: float
    evidence: tuple[str, ...]
    should_retrieve: bool


def decide_relevance(
    *,
    subject: str,
    body_text: str,
    attachment_filenames: list[str],
    detected_document_types: list[str],
    deterministic_match_evidence: list[str] | None = None,
) -> RelevanceDecision:
    normalized = _normalize(" ".join([subject, body_text, *attachment_filenames]))
    term_hits = sorted(term for term in TRAVEL_TERMS if _contains_phrase(normalized, term))
    evidence = list(dict.fromkeys(deterministic_match_evidence or []))
    has_document_like_file = any(
        filename.casefold().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp"))
        for filename in attachment_filenames
    )
    recognized_types = sorted(
        {
            document_type
            for document_type in detected_document_types
            if document_type in {"visa", "flight_ticket", "passport"}
        }
    )
    if recognized_types:
        evidence.extend(f"document_type_{value}" for value in recognized_types)
        confidence = (
            0.98
            if any(
                item in evidence for item in {"passport_number_exact", "group_upload_token_exact"}
            )
            else 0.94
        )
        return RelevanceDecision(
            status="relevant",
            confidence=confidence,
            evidence=tuple(dict.fromkeys(evidence)),
            should_retrieve=True,
        )

    if any(item in evidence for item in STRONG_GROUP_EVIDENCE):
        return RelevanceDecision(
            status="relevant",
            confidence=0.9,
            evidence=tuple(dict.fromkeys(evidence)),
            should_retrieve=True,
        )

    if any(item in evidence for item in GROUP_CONTEXT_EVIDENCE):
        evidence.extend(f"term_{term.replace(' ', '_')}" for term in term_hits[:5])
        return RelevanceDecision(
            status="possibly_relevant",
            confidence=0.78,
            evidence=tuple(dict.fromkeys(evidence)),
            should_retrieve=has_document_like_file,
        )

    if has_document_like_file and term_hits:
        evidence.extend(f"term_{term.replace(' ', '_')}" for term in term_hits[:5])
        evidence.append("document_attachment")
        return RelevanceDecision(
            status="possibly_relevant",
            confidence=0.68,
            evidence=tuple(dict.fromkeys(evidence)),
            should_retrieve=True,
        )
    if has_document_like_file:
        return RelevanceDecision(
            status="possibly_relevant",
            confidence=0.5,
            evidence=("document_attachment",),
            should_retrieve=True,
        )
    if len(term_hits) >= 2:
        evidence.extend(f"term_{term.replace(' ', '_')}" for term in term_hits[:5])
        return RelevanceDecision(
            status="possibly_relevant",
            confidence=0.55,
            evidence=tuple(dict.fromkeys(evidence)),
            should_retrieve=False,
        )
    return RelevanceDecision(
        status="unrelated",
        confidence=0.9,
        evidence=(),
        should_retrieve=False,
    )


def has_group_context_evidence(evidence: tuple[str, ...] | list[str]) -> bool:
    """Return whether a decision is anchored to an active group or roster."""

    return any(item in GROUP_CONTEXT_EVIDENCE for item in evidence)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _contains_phrase(haystack: str, needle: str) -> bool:
    return f" {needle} " in f" {haystack} "
