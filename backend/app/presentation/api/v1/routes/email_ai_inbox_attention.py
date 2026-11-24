"""Attention for the owner-scoped email inbox."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
)
from app.presentation.api.v1.routes.email_ai_inbox_types import SettingsProvider


async def _refresh_analysis_attention(
    session: AsyncSession,
    analysis: EmailAiAnalysisModel,
    get_settings: SettingsProvider,
) -> None:
    open_proposals = int(
        await session.scalar(
            select(func.count(EmailActionProposalModel.id)).where(
                EmailActionProposalModel.analysis_id == analysis.id,
                EmailActionProposalModel.agency_id == analysis.agency_id,
                EmailActionProposalModel.owner_user_id == analysis.owner_user_id,
                EmailActionProposalModel.status.in_({"proposed", "approval_required", "blocked"}),
            )
        )
        or 0
    )
    review_deadlines = int(
        await session.scalar(
            select(func.count(EmailDetectedDeadlineModel.id)).where(
                EmailDetectedDeadlineModel.analysis_id == analysis.id,
                EmailDetectedDeadlineModel.agency_id == analysis.agency_id,
                EmailDetectedDeadlineModel.owner_user_id == analysis.owner_user_id,
                EmailDetectedDeadlineModel.status == "review_required",
            )
        )
        or 0
    )
    result = analysis.result_json or {}
    settings = get_settings()
    candidate_links = result.get("candidate_links")
    low_confidence_link = bool(
        isinstance(candidate_links, list)
        and any(
            isinstance(link, dict)
            and isinstance(link.get("confidence"), (int, float))
            and float(link["confidence"]) < settings.email_ai_auto_confidence_threshold
            for link in candidate_links
        )
    )
    intrinsic_review = bool(
        not result.get("human_review_confirmed")
        and (
            result.get("relevance") == "possibly_relevant"
            or analysis.priority == "urgent"
            or analysis.intent in {"cancellation", "payment"}
            or (
                analysis.confidence is not None
                and analysis.confidence < settings.email_ai_auto_confidence_threshold
            )
            or low_confidence_link
            or result.get("candidate_ambiguity") is True
            or result.get("human_correction_pending") is True
            or _has_high_risk(result.get("risks"))
        )
    )
    analysis.needs_attention = bool(open_proposals or review_deadlines or intrinsic_review)
    if analysis.status == "review_required" and not analysis.needs_attention:
        analysis.status = "completed"
    analysis.updated_at = datetime.now(tz=UTC)
    await session.flush()


def _has_high_risk(value: object) -> bool:
    if not isinstance(value, list):
        return False
    return any(
        isinstance(item, dict) and item.get("level") in {"high", "critical"} for item in value
    )
