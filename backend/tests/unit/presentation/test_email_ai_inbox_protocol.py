"""Inbox pagination and response boundaries independent of mailbox/provider IO."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.presentation.api.v1.routes import email_ai_inbox as inbox


def test_cursor_roundtrip_preserves_priority_time_and_tie_break() -> None:
    identifier = uuid.uuid4()
    timestamp = datetime(2026, 10, 30, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    for priority, expected_rank in [("urgent", 0), ("high", 1), ("normal", 2), (None, 3)]:
        cursor = inbox._encode_cursor(priority, timestamp, identifier)
        rank, restored, restored_id = inbox._decode_cursor(cursor)
        assert rank == expected_rank
        assert restored == timestamp
        assert restored_id == identifier
    naive = datetime(2026, 10, 30, 12, 0)
    assert inbox._decode_cursor(inbox._encode_cursor("normal", naive, identifier))[
        1
    ] == naive.replace(tzinfo=UTC)


def test_malformed_cursor_has_a_static_validation_error() -> None:
    valid = {"priority_rank": 2, "updated_at": "2026-10-30T12:00:00+00:00", "id": str(uuid.uuid4())}
    malformed = ["not-a-valid-cursor", "", "!!!!"]
    for payload in [
        [],
        {},
        {**valid, "priority_rank": 9},
        {**valid, "priority_rank": float("inf")},
        {**valid, "id": "invalid"},
        {**valid, "updated_at": "2026-10-30"},
    ]:
        malformed.append(base64.urlsafe_b64encode(json.dumps(payload).encode()).decode())
    for cursor in malformed:
        with pytest.raises(HTTPException) as error:
            inbox._decode_cursor(cursor)
        assert error.value.status_code == 422
        assert error.value.detail == "Invalid inbox cursor."


def test_projection_preserves_safe_actions_visibility_and_provider_data_boundaries() -> None:
    now = datetime.now(tz=UTC)
    analysis = EmailAiAnalysisModel(
        id=uuid.uuid4(),
        status="completed",
        summary="Ready",
        priority="normal",
        confidence=0.9,
        needs_attention=False,
        ai_model="synthetic-model",
        prompt_schema_version="v1",
        updated_at=now,
        result_json={
            "linked_group_id": str(uuid.uuid4()),
            "risks": [
                {"code": "possible_mismatch", "level": "high", "rationale": "x" * 800},
                {"code": 3},
            ],
            "evidence": [{"unsupported": "must not be exposed"}, "visible evidence"],
            "missing_information": "unsupported scalar",
        },
    )
    response = inbox._intelligence_response(
        analysis,
        [],
        [],
        None,
        visible_group_id=None,
        visible_group_name=None,
        visible_passengers=[],
        candidate_links=[],
    )
    assert response.linked_group_id is None
    assert response.linked_passenger_ids == []
    assert response.evidence == ["visible evidence"]
    assert response.missing_information == []
    assert len(response.risks) == 1 and len(response.risks[0]) == 500
    assert "must not be exposed" not in response.model_dump_json()

    for status, risk, expected in [
        ("blocked", "low", ["reject", "dismiss"]),
        ("approval_required", "critical", ["reject", "dismiss"]),
        ("proposed", "low", ["approve", "reject", "dismiss"]),
        ("completed", "low", []),
    ]:
        proposal = EmailActionProposalModel(
            id=uuid.uuid4(),
            action_type="review",
            status=status,
            risk_level=risk,
            explanation="Synthetic",
            confidence=0.9,
            requires_approval=True,
            revision=1,
        )
        assert inbox._proposal_response(proposal).allowed_actions == expected

    message = EmailMessageModel(id=uuid.uuid4(), subject="Synthetic", received_at=now)
    connection = EmailConnectionModel(
        id=uuid.uuid4(), email_address="synthetic@example.invalid", provider="gmail"
    )
    for status, expected in [
        ("pending", "waiting"),
        ("completed", "completed_automatically"),
        ("ignored", "all_activity"),
    ]:
        analysis.status = status
        item = inbox._inbox_item(
            analysis=analysis,
            message=message,
            connection=connection,
            visible_group_id=None,
            group_name=None,
            deadlines=[],
            proposals=[],
            draft=None,
            now=now,
            deadline_window_days=7,
        )
        assert item.section == expected
    draft = EmailReplyDraftModel(status="prepared")
    assert (
        inbox._inbox_item(
            analysis=analysis,
            message=message,
            connection=connection,
            visible_group_id=None,
            group_name=None,
            deadlines=[],
            proposals=[],
            draft=draft,
            now=now,
            deadline_window_days=7,
        ).section
        == "drafts_ready"
    )
