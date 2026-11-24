"""Bounded correction labels and activity records for email inbox decisions."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailActivityEventModel
from app.presentation.api.v1.routes.email_ai_inbox_responses import _aware_utc


def _analysis_feedback_snapshot(
    analysis: EmailAiAnalysisModel,
) -> dict[str, object]:
    result_json = analysis.result_json or {}
    return {
        "status": analysis.status,
        "summary": analysis.summary,
        "intent": analysis.intent,
        "priority": analysis.priority,
        "needs_attention": analysis.needs_attention,
        "linked_group_id": result_json.get("linked_group_id"),
        "linked_passenger_ids": result_json.get(
            "linked_passenger_ids",
            [],
        ),
    }


_CORRECTION_ACTIVITY_VALUE_MAX_CHARS = 240


def _correction_activity_display_values(
    *,
    field_name: str,
    original_value: dict[str, object],
    corrected_value: dict[str, object],
) -> tuple[str, str]:
    """Render bounded operator-facing values from the persisted snapshots."""

    if field_name == "summary":
        return (
            _bounded_correction_text(
                original_value.get("summary"),
                empty="No summary",
            ),
            _bounded_correction_text(
                corrected_value.get("summary"),
                empty="No summary",
            ),
        )
    if field_name in {"intent", "priority"}:
        return (
            _bounded_correction_label(
                original_value.get(field_name),
                empty="Not set",
            ),
            _bounded_correction_label(
                corrected_value.get(field_name),
                empty="Not set",
            ),
        )
    if field_name == "linked_group":
        return (
            _group_snapshot_label(original_value),
            _group_snapshot_label(corrected_value),
        )
    if field_name == "linked_passengers":
        return (
            _passenger_snapshot_label(original_value),
            _passenger_snapshot_label(corrected_value),
        )
    if field_name == "deadline":
        return (
            _deadline_snapshot_label(original_value),
            _deadline_snapshot_label(corrected_value),
        )
    if field_name == "notification":
        return (
            _notification_snapshot_label(original_value),
            _notification_snapshot_label(corrected_value),
        )
    return "Previous value", "Corrected value"


def _bounded_correction_text(
    value: object,
    *,
    empty: str,
) -> str:
    if not isinstance(value, str):
        return empty
    normalized = " ".join(value.split())
    if not normalized:
        return empty
    if len(normalized) <= _CORRECTION_ACTIVITY_VALUE_MAX_CHARS:
        return normalized
    return normalized[: _CORRECTION_ACTIVITY_VALUE_MAX_CHARS - 1].rstrip() + "…"


def _bounded_correction_label(
    value: object,
    *,
    empty: str,
) -> str:
    if not isinstance(value, str):
        return empty
    return _bounded_correction_text(
        value.replace("_", " ").strip().title(),
        empty=empty,
    )


def _group_snapshot_label(value: dict[str, object]) -> str:
    name = value.get("group_name")
    if isinstance(name, str) and name.strip():
        return _bounded_correction_text(name, empty="Linked group")
    return "Linked group" if value.get("group_id") else "No linked group"


def _passenger_snapshot_label(value: dict[str, object]) -> str:
    names = value.get("passenger_names")
    if isinstance(names, list):
        safe_names = [
            " ".join(name.split()) for name in names if isinstance(name, str) and name.strip()
        ][:20]
        if safe_names:
            return _bounded_correction_text(
                ", ".join(safe_names),
                empty="No linked passengers",
            )
    passenger_ids = value.get("passenger_ids")
    count = len(passenger_ids) if isinstance(passenger_ids, list) else 0
    if count:
        return f"{min(count, 20)} linked passenger(s)"
    return "No linked passengers"


def _deadline_snapshot_label(value: dict[str, object]) -> str:
    due_at = value.get("due_at")
    if not isinstance(due_at, str) or not due_at.strip():
        return "No deadline"
    try:
        parsed = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    except ValueError:
        return "Previous deadline" if value.get("deadline_id") else "No deadline"
    normalized = _aware_utc(parsed)
    if normalized is None:
        return "No deadline"
    return normalized.strftime("%Y-%m-%d %H:%M UTC")


def _notification_snapshot_label(value: dict[str, object]) -> str:
    expected = value.get("notification_expected")
    if expected is True:
        return "Notification expected"
    if expected is False:
        return "No notification expected"
    return "Not specified"


def _decision_activity_event(
    *,
    analysis: EmailAiAnalysisModel,
    actor_user_id: uuid.UUID,
    event_key: str,
    event_type: str,
    summary_code: str,
    details: dict[str, object],
    changed_entity_type: str,
    changed_entity_id: uuid.UUID,
    confidence: float | None,
) -> EmailActivityEventModel:
    return EmailActivityEventModel(
        agency_id=analysis.agency_id,
        owner_user_id=analysis.owner_user_id,
        connection_id=analysis.connection_id,
        message_id=analysis.message_id,
        event_key=event_key,
        event_type=event_type,
        stage="info",
        actor_type="user",
        actor_user_id=actor_user_id,
        summary_code=summary_code,
        details=details,
        ai_used=True,
        ai_provider=analysis.ai_provider,
        ai_model=analysis.ai_model,
        confidence=confidence,
        changed_entity_type=changed_entity_type,
        changed_entity_id=changed_entity_id,
    )
