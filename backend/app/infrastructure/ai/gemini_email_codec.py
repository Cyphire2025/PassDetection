"""Strict provider envelope parsing and status/alias classification."""

from __future__ import annotations

import httpx

from app.domain.value_objects.email_ai_analysis import (
    EmailAnalysisProviderStatus,
    EmailAnalysisRequest,
    GeminiEmailAnalysisPayload,
)


def parse_email_analysis_response(
    response: httpx.Response,
    *,
    maximum_response_bytes: int,
    maximum_text_characters: int,
    maximum_thought_signature_characters: int,
) -> GeminiEmailAnalysisPayload:
    if len(response.content) > maximum_response_bytes:
        raise ValueError("provider response exceeded byte bound")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("provider response must be an object")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("provider response must contain one candidate")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ValueError("provider candidate must be an object")
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ValueError("provider content must be an object")
    parts = content.get("parts")
    if not isinstance(parts, list) or len(parts) != 1:
        raise ValueError("provider content must contain one part")
    part = parts[0]
    if not isinstance(part, dict) or not set(part).issubset({"text", "thoughtSignature"}):
        raise ValueError("provider part contains unexpected fields")
    text = part.get("text")
    if not isinstance(text, str) or len(text) > maximum_text_characters:
        raise ValueError("provider text must be a bounded string")
    thought_signature = part.get("thoughtSignature")
    if thought_signature is not None and (
        not isinstance(thought_signature, str)
        or len(thought_signature) > maximum_thought_signature_characters
    ):
        raise ValueError("provider thought signature must be bounded")
    return GeminiEmailAnalysisPayload.model_validate_json(text)


def _require_visible_aliases(
    result: GeminiEmailAnalysisPayload,
    request: EmailAnalysisRequest,
) -> None:
    visible_aliases = {candidate.alias for candidate in request.visible_candidates}
    returned_aliases = {link.alias for link in result.candidate_links}
    returned_aliases.update(
        proposal.target_alias for proposal in result.proposals if proposal.target_alias is not None
    )
    if not returned_aliases.issubset(visible_aliases):
        raise ValueError("provider returned an alias outside the allowlist")


def _provider_failure(
    status_code: int,
) -> tuple[EmailAnalysisProviderStatus, str] | None:
    if status_code == 429 or status_code >= 500:
        return (
            EmailAnalysisProviderStatus.PROVIDER_UNAVAILABLE,
            "provider_unavailable",
        )
    if status_code >= 300:
        return (
            EmailAnalysisProviderStatus.PROVIDER_REJECTED,
            "provider_rejected_request",
        )
    return None
