"""Typed owner-scoped inbox corrections within the caller's transaction."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.presentation.api.v1.routes.email_ai_inbox_responses import _aware_utc, _result_group_id
from app.presentation.api.v1.routes.email_ai_inbox_scope import _owner_predicates
from app.presentation.api.v1.schemas.email_ai_schemas import EmailAiFeedbackRequest


async def _apply_typed_correction(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    payload: EmailAiFeedbackRequest,
    current_user: User,
    now: datetime,
) -> tuple[dict[str, object], dict[str, object]]:
    """Apply one owner-scoped correction and return audited before/after values."""

    correction = payload.correction
    if correction is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A typed correction is required.",
        )
    result_json = dict(analysis.result_json or {})
    field_name = payload.field_name
    original: dict[str, object]

    if field_name == "summary":
        corrected_summary = (correction.text or "").strip()
        original = {"summary": analysis.summary}
        analysis.summary = corrected_summary
        result_json["summary"] = corrected_summary
        analysis.result_json = result_json
        return original, {"summary": corrected_summary}

    if field_name == "intent":
        original = {"intent": analysis.intent}
        analysis.intent = correction.intent
        result_json["intent"] = correction.intent
        analysis.result_json = result_json
        return original, {"intent": correction.intent}

    if field_name == "priority":
        original = {"priority": analysis.priority}
        analysis.priority = correction.priority
        result_json["priority"] = correction.priority
        analysis.result_json = result_json
        return original, {"priority": correction.priority}

    if field_name == "linked_group":
        group = await _visible_correction_group(
            session,
            analysis=analysis,
            group_id=correction.group_id,
            current_user=current_user,
        )
        original = {
            "group_id": result_json.get("linked_group_id"),
            "passenger_ids": result_json.get("linked_passenger_ids", []),
        }
        result_json["linked_group_id"] = str(group.id)
        # A passenger link cannot survive a parent-group correction without
        # being explicitly reselected and revalidated.
        result_json["linked_passenger_ids"] = []
        analysis.result_json = result_json
        return original, {
            "group_id": str(group.id),
            "group_name": group.name,
            "passenger_ids": [],
        }

    if field_name == "linked_passengers":
        passenger_ids = list(dict.fromkeys(correction.passenger_ids or []))
        original = {
            "group_id": result_json.get("linked_group_id"),
            "passenger_ids": result_json.get("linked_passenger_ids", []),
        }
        if not passenger_ids:
            result_json["linked_passenger_ids"] = []
            analysis.result_json = result_json
            return original, {"passenger_ids": []}

        statement = select(PassportSubmissionModel).where(
            PassportSubmissionModel.id.in_(passenger_ids),
            PassportSubmissionModel.agency_id == analysis.agency_id,
            PassportSubmissionModel.status != "failed",
        )
        passenger_result = await session.execute(
            AuthorizationPolicy.apply_passport_visibility_scope(
                statement,
                current_user,
            )
        )
        visible_passengers = {
            passenger.id: passenger for passenger in passenger_result.scalars().all()
        }
        if set(visible_passengers) != set(passenger_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more selected passengers are not available.",
            )
        group_ids = {passenger.group_id for passenger in visible_passengers.values()}
        if len(group_ids) != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Selected passengers must belong to one visible group.",
            )
        passenger_group_id = next(iter(group_ids))
        existing_group_id = _result_group_id(analysis)
        if existing_group_id is not None and existing_group_id != passenger_group_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Selected passengers do not belong to the linked group. "
                    "Correct the group first."
                ),
            )
        group = await _visible_correction_group(
            session,
            analysis=analysis,
            group_id=passenger_group_id,
            current_user=current_user,
        )
        result_json["linked_group_id"] = str(group.id)
        result_json["linked_passenger_ids"] = [str(passenger_id) for passenger_id in passenger_ids]
        analysis.result_json = result_json
        return original, {
            "group_id": str(group.id),
            "group_name": group.name,
            "passenger_ids": [str(passenger_id) for passenger_id in passenger_ids],
            "passenger_names": [
                visible_passengers[passenger_id].client_name for passenger_id in passenger_ids
            ],
        }

    if field_name == "deadline":
        due_at = _aware_utc(correction.due_at)
        if due_at is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A timezone-aware corrected deadline is required.",
            )
        deadline: EmailDetectedDeadlineModel | None = None
        if correction.deadline_id is not None:
            deadline = (
                await session.execute(
                    select(EmailDetectedDeadlineModel)
                    .where(
                        EmailDetectedDeadlineModel.id == correction.deadline_id,
                        EmailDetectedDeadlineModel.analysis_id == analysis.id,
                        EmailDetectedDeadlineModel.agency_id == analysis.agency_id,
                        EmailDetectedDeadlineModel.owner_user_id == analysis.owner_user_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if deadline is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="The selected deadline is not available.",
                )
            original = {
                "deadline_id": str(deadline.id),
                "due_at": (
                    _aware_utc(deadline.due_at).isoformat() if deadline.due_at is not None else None
                ),
                "status": deadline.status,
            }
            deadline.due_at = due_at
            deadline.confidence = 1.0
            deadline.is_ambiguous = False
            deadline.status = "review_required"
            deadline.resolution_evidence = {
                "source": "human_correction",
                "corrected_by_user_id": str(current_user.id),
                "corrected_at": now.isoformat(),
            }
            deadline.updated_at = now
        else:
            deadline_id = uuid.uuid4()
            deadline = EmailDetectedDeadlineModel(
                id=deadline_id,
                agency_id=analysis.agency_id,
                owner_user_id=analysis.owner_user_id,
                connection_id=analysis.connection_id,
                message_id=analysis.message_id,
                analysis_id=analysis.id,
                deadline_type="human_corrected",
                source_phrase="Deadline added by the mailbox owner.",
                source_fingerprint=hashlib.sha256(
                    f"human-correction:{deadline_id}".encode()
                ).hexdigest(),
                source_timezone="UTC",
                due_at=due_at,
                confidence=1.0,
                is_ambiguous=False,
                status="review_required",
                resolution_evidence={
                    "source": "human_correction",
                    "corrected_by_user_id": str(current_user.id),
                    "corrected_at": now.isoformat(),
                },
            )
            session.add(deadline)
            original = {"deadline_id": None, "due_at": None}
        await session.flush()
        return original, {
            "deadline_id": str(deadline.id),
            "due_at": due_at.isoformat(),
            "status": deadline.status,
        }

    if field_name == "notification":
        original = {
            "notification_expected": result_json.get("human_notification_expected"),
            "needs_attention": analysis.needs_attention,
        }
        expected = bool(correction.notification_expected)
        result_json["human_notification_expected"] = expected
        result_json["human_notification_preference_recorded_at"] = now.isoformat()
        analysis.result_json = result_json
        return original, {"notification_expected": expected}

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="Unsupported correction field.",
    )


async def _invalidate_generated_work_after_correction(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    field_name: str,
    current_user: User,
    now: datetime,
) -> bool:
    """Fail closed on generated work whose premises changed."""

    if field_name == "notification":
        return False
    proposal_rows = (
        (
            await session.execute(
                select(EmailActionProposalModel)
                .where(
                    EmailActionProposalModel.analysis_id == analysis.id,
                    *_owner_predicates(
                        EmailActionProposalModel,
                        current_user,
                    ),
                    EmailActionProposalModel.status.in_(
                        {"proposed", "approval_required", "blocked"}
                    ),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    draft_rows = (
        (
            await session.execute(
                select(EmailReplyDraftModel)
                .where(
                    EmailReplyDraftModel.analysis_id == analysis.id,
                    *_owner_predicates(
                        EmailReplyDraftModel,
                        current_user,
                    ),
                    EmailReplyDraftModel.status.in_({"prepared", "edited", "approved"}),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for proposal in proposal_rows:
        proposal.status = "dismissed"
        proposal.revision += 1
        proposal.decision_by_user_id = current_user.id
        proposal.decision_at = now
        proposal.decision_note = "Invalidated because a human corrected the AI brief."
        proposal.updated_at = now
    for draft in draft_rows:
        draft.status = "dismissed"
        draft.revision += 1
        draft.edited_by_user_id = current_user.id
        draft.updated_at = now
    return bool(proposal_rows or draft_rows)


async def _visible_correction_group(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    group_id: uuid.UUID | None,
    current_user: User,
) -> ClientGroupModel:
    if group_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A group selection is required.",
        )
    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == analysis.agency_id,
        ClientGroupModel.status.notin_({"archived", "deleted"}),
    )
    group = (
        await session.execute(
            AuthorizationPolicy.apply_group_visibility_scope(
                statement,
                current_user,
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected group is not available.",
        )
    return cast(ClientGroupModel, group)
