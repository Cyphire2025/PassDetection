"""Transactional metadata-only analysis activity and personally targeted attention."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    EmailAnalysisResult,
    EmailRelevance,
)
from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.email.ai_values import _aware_utc, _manual_retry_generation
from app.infrastructure.repositories.notification_repository import NotificationRepository


async def _record_analysis_activity(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    result: EmailAnalysisResult,
) -> None:
    retry_generation = _manual_retry_generation(analysis)
    session.add(
        EmailActivityEventModel(
            agency_id=analysis.agency_id,
            owner_user_id=analysis.owner_user_id,
            connection_id=analysis.connection_id,
            message_id=analysis.message_id,
            event_key=(f"email-ai:{analysis.id}:completed:{retry_generation}"),
            event_type="ai_analysis_completed",
            stage=("warning" if analysis.status in {"review_required", "failed"} else "success"),
            actor_type="system",
            summary_code=f"email_ai_{analysis.status}",
            details={
                "analysis_id": str(analysis.id),
                "provider_status": result.provider_status.value,
                "priority": result.priority.value,
                "needs_review": result.needs_review,
                "proposal_count": len(result.proposals),
                "deadline_count": len(result.deadlines),
                "retry_generation": retry_generation,
            },
            ai_used=True,
            ai_provider="google",
            ai_model=result.model,
            confidence=result.confidence,
            changed_entity_type="email_ai_analysis",
            changed_entity_id=analysis.id,
        )
    )


async def _create_attention_notification(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    message: EmailMessageModel,
    connection: EmailConnectionModel,
    result: EmailAnalysisResult,
    deadlines: list[EmailDetectedDeadlineModel],
    draft: EmailReplyDraftModel | None,
    proposal_count: int,
    notification_window_days: int,
    linked_group_name: str | None = None,
    notification_repository: Callable[[AsyncSession], NotificationRepository],
) -> None:
    high_risk = any(
        decision.risk_level.value in {"high", "critical"} for decision in result.action_decisions
    ) or any(risk.level.value in {"high", "critical"} for risk in result.risks)
    has_approval = any(
        decision.disposition == ActionDisposition.PROPOSAL_ONLY
        for decision in result.action_decisions
    )
    deadline_cutoff = datetime.now(tz=UTC) + timedelta(days=notification_window_days)
    actionable_deadlines = [
        deadline
        for deadline in deadlines
        if deadline.status == "review_required"
        or (deadline.due_at is not None and _aware_utc(deadline.due_at) <= deadline_cutoff)
    ]
    has_deadline = bool(actionable_deadlines)
    should_notify = (
        analysis.status == "failed"
        or result.needs_review
        or high_risk
        or has_approval
        or has_deadline
        or draft is not None
    )
    if not should_notify or result.relevance == EmailRelevance.UNRELATED:
        return
    priority = (
        "urgent"
        if high_risk or result.priority.value == "urgent"
        else "high"
        if result.needs_review or has_approval or result.priority.value == "high"
        else "normal"
    )
    if high_risk:
        title = "High-risk travel email needs review"
    elif has_approval:
        title = "Travel email action needs approval"
    elif has_deadline:
        title = "Travel deadline detected"
    elif draft is not None:
        title = "Prepared reply draft is ready"
    else:
        title = "Travel email needs attention"
    await notification_repository(session).create(
        agency_id=analysis.agency_id,
        user_id=analysis.owner_user_id,
        type="email_ai_attention",
        title=title,
        message=result.summary[:500],
        entity_type="email_message",
        entity_id=str(message.id),
        priority=priority,
        category="email_operations",
        dedupe_key=(f"email-ai:{analysis.id}:attention:{_manual_retry_generation(analysis)}"),
        metadata={
            "provider": connection.provider,
            "account_email": connection.email_address,
            "analysis_id": str(analysis.id),
            "deadline_count": len(actionable_deadlines),
            "proposal_count": proposal_count,
            "draft_ready": draft is not None,
            "retry_generation": _manual_retry_generation(analysis),
            **({"group_name": linked_group_name} if linked_group_name is not None else {}),
        },
    )
