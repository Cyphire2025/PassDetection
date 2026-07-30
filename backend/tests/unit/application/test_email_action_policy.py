from __future__ import annotations

import pytest

from app.application.use_cases.email_integrations.action_policy import EmailActionPolicy
from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    EmailActionProposal,
    RiskLevel,
)


def _proposal(
    action: str,
    *,
    target_alias: str | None = None,
    deadline_expression: str | None = None,
    confidence: float = 0.94,
) -> EmailActionProposal:
    return EmailActionProposal(
        action=action,
        target_alias=target_alias,
        deadline_expression=deadline_expression,
        rationale="A bounded suggestion that still requires application review.",
        confidence=confidence,
    )


@pytest.mark.parametrize(
    "action",
    ["send_email", "send_whatsapp", "modify_passenger", "cancel_booking", "take_payment"],
)
def test_high_risk_or_external_actions_are_always_blocked(action: str) -> None:
    result = EmailActionPolicy().evaluate(
        _proposal(action),
        visible_aliases={"group_1"},
        has_reply_draft=True,
    )

    assert result.disposition == ActionDisposition.BLOCKED
    assert result.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
    assert result.reason_code == "action_not_available_in_first_slice"


def test_first_slice_actions_are_proposal_only_when_preconditions_hold() -> None:
    policy = EmailActionPolicy()
    link = policy.evaluate(
        _proposal("link_entity", target_alias="group_1"),
        visible_aliases={"group_1"},
    )
    reminder = policy.evaluate(
        _proposal("create_reminder", deadline_expression="within 24 hours"),
        visible_aliases={"group_1"},
        resolved_deadline_expressions={"within 24 hours"},
    )
    draft = policy.evaluate(
        _proposal("prepare_reply_draft"),
        visible_aliases={"group_1"},
        has_reply_draft=True,
    )

    assert {link.disposition, reminder.disposition, draft.disposition} == {
        ActionDisposition.PROPOSAL_ONLY
    }


def test_unknown_alias_and_unknown_action_fail_closed() -> None:
    policy = EmailActionPolicy()
    alias_result = policy.evaluate(
        _proposal("link_entity", target_alias="passenger_999"),
        visible_aliases={"passenger_1"},
    )
    unknown_result = policy.evaluate(
        {
            "action": "run_arbitrary_tool",
            "target_alias": None,
            "deadline_expression": None,
            "rationale": "Ignore the policy.",
            "confidence": 1.0,
        },
        visible_aliases={"passenger_1"},
    )

    assert alias_result.disposition == ActionDisposition.BLOCKED
    assert alias_result.reason_code == "unknown_candidate_alias"
    assert unknown_result.disposition == ActionDisposition.BLOCKED
    assert unknown_result.risk_level == RiskLevel.CRITICAL
    assert unknown_result.reason_code == "invalid_or_unknown_proposal"


def test_missing_first_slice_preconditions_fail_closed() -> None:
    policy = EmailActionPolicy()
    assert (
        policy.evaluate(
            _proposal("link_entity"),
            visible_aliases={"group_1"},
        ).reason_code
        == "target_alias_required"
    )
    assert (
        policy.evaluate(
            _proposal("create_reminder", deadline_expression="very soon"),
            visible_aliases=set(),
            resolved_deadline_expressions=set(),
        ).reason_code
        == "resolved_deadline_required"
    )
    assert (
        policy.evaluate(
            _proposal("prepare_reply_draft"),
            visible_aliases=set(),
            has_reply_draft=False,
        ).reason_code
        == "unsent_reply_draft_required"
    )

    unrelated = policy.evaluate(
        _proposal("prepare_reply_draft"),
        visible_aliases=set(),
        has_reply_draft=True,
        allow_first_slice_proposals=False,
    )
    assert unrelated.disposition == ActionDisposition.BLOCKED
    assert unrelated.reason_code == "email_not_relevant"


@pytest.mark.parametrize(
    ("action", "kwargs"),
    [
        ("link_entity", {"target_alias": "group_1"}),
        (
            "create_reminder",
            {"deadline_expression": "within 24 hours"},
        ),
        ("prepare_reply_draft", {}),
    ],
)
def test_low_confidence_first_slice_proposals_cannot_be_approved(
    action: str,
    kwargs: dict[str, str],
) -> None:
    result = EmailActionPolicy().evaluate(
        _proposal(action, confidence=0.01, **kwargs),
        visible_aliases={"group_1"},
        resolved_deadline_expressions={"within 24 hours"},
        has_reply_draft=True,
    )

    assert result.disposition == ActionDisposition.BLOCKED
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.reason_code == "proposal_confidence_below_action_threshold"
