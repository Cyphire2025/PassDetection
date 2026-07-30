"""Fail-closed registry for AI-proposed travel inbox actions."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from pydantic import ValidationError

from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    ActionPolicyDecision,
    EmailActionProposal,
    EmailActionType,
    RiskLevel,
)


@dataclass(frozen=True)
class EmailActionDefinition:
    disposition: ActionDisposition
    risk_level: RiskLevel
    minimum_confidence: float = 1.0
    requires_target_alias: bool = False
    requires_resolved_deadline: bool = False
    requires_reply_draft: bool = False


_ACTION_REGISTRY: Final[dict[EmailActionType, EmailActionDefinition]] = {
    EmailActionType.LINK_ENTITY: EmailActionDefinition(
        disposition=ActionDisposition.PROPOSAL_ONLY,
        risk_level=RiskLevel.LOW,
        minimum_confidence=0.9,
        requires_target_alias=True,
    ),
    EmailActionType.CREATE_REMINDER: EmailActionDefinition(
        disposition=ActionDisposition.PROPOSAL_ONLY,
        risk_level=RiskLevel.LOW,
        minimum_confidence=0.9,
        requires_resolved_deadline=True,
    ),
    EmailActionType.PREPARE_REPLY_DRAFT: EmailActionDefinition(
        disposition=ActionDisposition.PROPOSAL_ONLY,
        risk_level=RiskLevel.LOW,
        minimum_confidence=0.8,
        requires_reply_draft=True,
    ),
    EmailActionType.SEND_EMAIL: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.HIGH,
    ),
    EmailActionType.SEND_WHATSAPP: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.HIGH,
    ),
    EmailActionType.MODIFY_PASSENGER: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.HIGH,
    ),
    EmailActionType.REPLACE_PASSENGER: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
    ),
    EmailActionType.CANCEL_BOOKING: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
    ),
    EmailActionType.TAKE_PAYMENT: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
    ),
    EmailActionType.DELETE_RECORD: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
    ),
    EmailActionType.EXPORT_DATA: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
    ),
    EmailActionType.FETCH_EXTERNAL_URL: EmailActionDefinition(
        disposition=ActionDisposition.BLOCKED,
        risk_level=RiskLevel.HIGH,
    ),
}


class EmailActionPolicy:
    """Classify provider proposals without ever executing them."""

    def evaluate(
        self,
        proposal: EmailActionProposal | Mapping[str, Any],
        *,
        visible_aliases: Iterable[str],
        resolved_deadline_expressions: Iterable[str] = (),
        has_reply_draft: bool = False,
        allow_first_slice_proposals: bool = True,
        link_confidence_threshold: float = 0.9,
    ) -> ActionPolicyDecision:
        if not 0 <= link_confidence_threshold <= 1:
            raise ValueError("link_confidence_threshold must be between 0 and 1")
        parsed = self._parse_proposal(proposal)
        if parsed is None:
            return ActionPolicyDecision(
                action=self._raw_action_name(proposal),
                disposition=ActionDisposition.BLOCKED,
                risk_level=RiskLevel.CRITICAL,
                reason_code="invalid_or_unknown_proposal",
                target_alias=None,
            )

        definition = _ACTION_REGISTRY.get(parsed.action)
        if definition is None:
            return ActionPolicyDecision(
                action=parsed.action.value,
                disposition=ActionDisposition.BLOCKED,
                risk_level=RiskLevel.CRITICAL,
                reason_code="unknown_action",
                target_alias=parsed.target_alias,
            )

        alias_allowlist = frozenset(visible_aliases)
        if parsed.target_alias is not None and parsed.target_alias not in alias_allowlist:
            return ActionPolicyDecision(
                action=parsed.action.value,
                disposition=ActionDisposition.BLOCKED,
                risk_level=RiskLevel.CRITICAL,
                reason_code="unknown_candidate_alias",
                target_alias=parsed.target_alias,
            )
        if definition.requires_target_alias and parsed.target_alias is None:
            return ActionPolicyDecision(
                action=parsed.action.value,
                disposition=ActionDisposition.BLOCKED,
                risk_level=RiskLevel.HIGH,
                reason_code="target_alias_required",
                target_alias=None,
            )

        if definition.disposition == ActionDisposition.BLOCKED:
            return ActionPolicyDecision(
                action=parsed.action.value,
                disposition=ActionDisposition.BLOCKED,
                risk_level=definition.risk_level,
                reason_code="action_not_available_in_first_slice",
                target_alias=parsed.target_alias,
            )

        if not allow_first_slice_proposals:
            return ActionPolicyDecision(
                action=parsed.action.value,
                disposition=ActionDisposition.BLOCKED,
                risk_level=RiskLevel.HIGH,
                reason_code="email_not_relevant",
                target_alias=parsed.target_alias,
            )

        minimum_confidence = (
            link_confidence_threshold
            if parsed.action == EmailActionType.LINK_ENTITY
            else definition.minimum_confidence
        )
        if parsed.confidence < minimum_confidence:
            return ActionPolicyDecision(
                action=parsed.action.value,
                disposition=ActionDisposition.BLOCKED,
                risk_level=RiskLevel.MEDIUM,
                reason_code="proposal_confidence_below_action_threshold",
                target_alias=parsed.target_alias,
            )

        if definition.requires_resolved_deadline:
            resolved_expressions = frozenset(resolved_deadline_expressions)
            if (
                parsed.deadline_expression is None
                or parsed.deadline_expression not in resolved_expressions
            ):
                return ActionPolicyDecision(
                    action=parsed.action.value,
                    disposition=ActionDisposition.BLOCKED,
                    risk_level=RiskLevel.HIGH,
                    reason_code="resolved_deadline_required",
                    target_alias=parsed.target_alias,
                )

        if definition.requires_reply_draft and not has_reply_draft:
            return ActionPolicyDecision(
                action=parsed.action.value,
                disposition=ActionDisposition.BLOCKED,
                risk_level=RiskLevel.HIGH,
                reason_code="unsent_reply_draft_required",
                target_alias=parsed.target_alias,
            )

        return ActionPolicyDecision(
            action=parsed.action.value,
            disposition=ActionDisposition.PROPOSAL_ONLY,
            risk_level=definition.risk_level,
            reason_code="proposal_recording_allowed",
            target_alias=parsed.target_alias,
        )

    @staticmethod
    def _parse_proposal(
        proposal: EmailActionProposal | Mapping[str, Any],
    ) -> EmailActionProposal | None:
        if isinstance(proposal, EmailActionProposal):
            return proposal
        try:
            return EmailActionProposal.model_validate(dict(proposal))
        except (TypeError, ValueError, ValidationError):
            return None

    @staticmethod
    def _raw_action_name(proposal: EmailActionProposal | Mapping[str, Any]) -> str:
        if isinstance(proposal, EmailActionProposal):
            return proposal.action.value
        raw_action = proposal.get("action")
        if not isinstance(raw_action, str):
            return "unknown"
        normalized = re.sub(
            r"[^a-z0-9_-]+",
            "_",
            raw_action[:256].casefold(),
        ).strip("_")
        return normalized[:64] or "unknown"


def registered_action_types() -> frozenset[EmailActionType]:
    """Expose a read-only registry view for schema/evaluation tooling."""

    return frozenset(_ACTION_REGISTRY)
