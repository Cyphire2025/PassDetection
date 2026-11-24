"""Bounded text minimization and exact visible deadline grounding."""

from __future__ import annotations

import re
import unicodedata

from app.domain.value_objects.email_ai_analysis import (
    DeadlineCandidate,
    DeadlineResolutionStatus,
    EmailAnalysisRequest,
    ResolvedDeadline,
)
from app.infrastructure.ai.gemini_email_patterns import (
    _DOB_PATTERN,
    _EMAIL_PATTERN,
    _INTERNATIONAL_PHONE_PATTERN,
    _PASSPORT_PATTERN,
    _PHONE_PATTERN,
    _SAFE_DEADLINE_DERIVATIONS,
    _URL_PATTERN,
)


def _minimize_text(value: str, *, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character
        for character in normalized
        if character in {"\n", "\t"} or not unicodedata.category(character).startswith("C")
    )
    normalized = _EMAIL_PATTERN.sub("[email removed]", normalized)
    normalized = _URL_PATTERN.sub("[link removed]", normalized)
    normalized = _PASSPORT_PATTERN.sub("passport [identifier removed]", normalized)
    normalized = _DOB_PATTERN.sub("date of birth [removed]", normalized)
    normalized = _PHONE_PATTERN.sub("contact [removed]", normalized)
    normalized = _INTERNATIONAL_PHONE_PATTERN.sub("[phone removed]", normalized)
    return normalized[:max_length]


def _trusted_fact_corpus(request: EmailAnalysisRequest) -> str:
    """Mirror the bounded, sanitized factual text exposed to the provider."""

    parts = [
        _minimize_text(request.subject, max_length=500),
        _minimize_text(request.body_text, max_length=12_000),
        *(
            [_minimize_text(request.sender_display_name, max_length=160)]
            if request.sender_display_name is not None
            else []
        ),
        request.sender_domain or "",
        *request.recipient_domains,
        request.connected_account_domain or "",
        *[_minimize_text(filename, max_length=160) for filename in request.attachment_filenames],
    ]
    for candidate in request.visible_candidates:
        parts.extend(
            (
                candidate.alias,
                candidate.entity_type.value,
                *(_minimize_text(fact, max_length=160) for fact in candidate.safe_facts),
            )
        )
    normalized_message = f"{request.subject}\n{request.body_text}".casefold()
    if "kal shaam tak" in normalized_message:
        # The deterministic deadline resolver treats this one bounded
        # Hinglish phrase as a future "tomorrow evening" expression.
        parts.append("tomorrow evening")
    return "\n".join(parts)


def _deadline_is_grounded_in_email(
    candidate: DeadlineCandidate,
    request: EmailAnalysisRequest,
) -> bool:
    """Require a visible phrase before deterministic deadline resolution."""

    bounded_email = _normalize_visible_phrase(
        "\n".join(
            (
                _minimize_text(request.subject, max_length=500),
                _minimize_text(request.body_text, max_length=12_000),
            )
        )
    )
    source_text = _normalize_visible_phrase(candidate.source_text)
    if not source_text or source_text not in bounded_email:
        return False
    expression = _normalize_visible_phrase(candidate.expression)
    if expression and expression in source_text:
        return True
    return any(
        supported_phrase in source_text
        for supported_phrase in _SAFE_DEADLINE_DERIVATIONS.get(
            expression,
            frozenset(),
        )
    )


def _normalize_visible_phrase(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _ungrounded_deadline(candidate: DeadlineCandidate) -> ResolvedDeadline:
    return ResolvedDeadline(
        source_text=candidate.source_text,
        expression=candidate.expression,
        confidence=candidate.confidence,
        status=DeadlineResolutionStatus.REVIEW_REQUIRED,
        due_at=None,
        reason_code="deadline_not_grounded_in_email",
    )
