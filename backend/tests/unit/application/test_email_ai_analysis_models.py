from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.value_objects.email_ai_analysis import (
    EmailAnalysisRequest,
    GeminiEmailAnalysisPayload,
    UnsentReplyDraft,
    VisibleEmailCandidate,
)


def _provider_payload() -> dict[str, object]:
    return {
        "relevance": "relevant",
        "intent": "document_submission",
        "priority": "high",
        "confidence": 0.95,
        "summary": "A visa document was submitted for review.",
        "candidate_links": [
            {
                "alias": "group_1",
                "confidence": 0.96,
                "rationale": "The bounded candidate facts match the group reference.",
            }
        ],
        "deadlines": [],
        "risks": [],
        "missing_information": [],
        "proposals": [
            {
                "action": "link_entity",
                "target_alias": "group_1",
                "deadline_expression": None,
                "rationale": "Record a proposed association for staff review.",
                "confidence": 0.96,
            }
        ],
        "reply_draft": None,
    }


def test_provider_schema_forbids_extra_fields_at_every_level() -> None:
    payload = _provider_payload()
    payload["unexpected"] = "not allowed"
    with pytest.raises(ValidationError):
        GeminiEmailAnalysisPayload.model_validate(payload)

    nested_payload = _provider_payload()
    candidate_link = nested_payload["candidate_links"][0]  # type: ignore[index]
    candidate_link["database_id"] = "private-id"  # type: ignore[index]
    with pytest.raises(ValidationError):
        GeminiEmailAnalysisPayload.model_validate(nested_payload)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_provider_schema_bounds_confidence(confidence: float) -> None:
    payload = _provider_payload()
    candidate_link = payload["candidate_links"][0]  # type: ignore[index]
    candidate_link["confidence"] = confidence  # type: ignore[index]
    with pytest.raises(ValidationError):
        GeminiEmailAnalysisPayload.model_validate(payload)

    payload = _provider_payload()
    payload["confidence"] = confidence
    with pytest.raises(ValidationError):
        GeminiEmailAnalysisPayload.model_validate(payload)


def test_provider_schema_rejects_malformed_and_unbounded_values() -> None:
    payload = _provider_payload()
    payload["summary"] = "x" * 601
    with pytest.raises(ValidationError):
        GeminiEmailAnalysisPayload.model_validate(payload)

    payload = _provider_payload()
    payload["candidate_links"] = [
        {
            "alias": "00000000-0000-0000-0000-000000000999",
            "confidence": 0.9,
            "rationale": "An arbitrary database identifier must never be accepted.",
        }
    ]
    with pytest.raises(ValidationError):
        GeminiEmailAnalysisPayload.model_validate(payload)


def test_reply_draft_can_only_be_unsent() -> None:
    draft = UnsentReplyDraft(
        subject="Re: Arrival details",
        body="Thank you. We will review the supplied details.",
        tone="professional",
        send_state="unsent",
    )
    assert draft.send_state.value == "unsent"

    with pytest.raises(ValidationError):
        UnsentReplyDraft(
            subject="Re: Arrival details",
            body="This must not be sent automatically.",
            tone="professional",
            send_state="sent",
        )


def test_analysis_request_requires_aware_time_and_unique_opaque_aliases() -> None:
    candidate = VisibleEmailCandidate(
        alias="group_1",
        entity_type="group",
        safe_facts=["Group reference ALPHA"],
    )
    request = EmailAnalysisRequest(
        subject="Visa update",
        body_text="Please review the attached visa.",
        received_at=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        timezone="Asia/Kolkata",
        visible_candidates=[candidate],
    )
    assert request.visible_candidates[0].alias == "group_1"

    with pytest.raises(ValidationError):
        EmailAnalysisRequest(
            subject="Visa update",
            body_text="Please review the attached visa.",
            received_at=datetime(2026, 7, 30, 8, 0),
            timezone="Asia/Kolkata",
            visible_candidates=[],
        )

    with pytest.raises(ValidationError):
        EmailAnalysisRequest(
            subject="Visa update",
            body_text="Please review the attached visa.",
            received_at=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
            timezone="Asia/Kolkata",
            visible_candidates=[candidate, candidate],
        )
