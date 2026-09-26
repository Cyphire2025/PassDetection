"""Describe classified-document rejection without changing match authority."""

from __future__ import annotations

from app.infrastructure.documents.document_matcher import ClassifiedDocument, MatchResult


def verification_rejection_reason(
    classification: ClassifiedDocument, *, is_uploadable: bool, feedback_match: MatchResult | None,
) -> str:
    rejection_reason = (
        feedback_match.reason
        if classification.accepted and not is_uploadable and feedback_match
        else "No passenger match found"
        if classification.accepted and not is_uploadable
        else classification.reason
    )
    return rejection_reason
