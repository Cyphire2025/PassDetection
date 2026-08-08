"""Review and activity display mapping for email-integration routes."""

from __future__ import annotations

from urllib.parse import quote

from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import PassportSubmissionModel


def _original_email_url(
    *,
    provider: str,
    account_email: str,
    provider_message_id: str,
) -> str | None:
    """Build an allowlisted provider deep link from server-owned identifiers."""

    if not provider_message_id or len(provider_message_id) > 512:
        return None
    encoded_message_id = quote(provider_message_id, safe="")
    if provider == "gmail":
        encoded_account = quote(account_email, safe="@.")
        return f"https://mail.google.com/mail/u/{encoded_account}/#all/{encoded_message_id}"
    if provider == "outlook":
        return f"https://outlook.office.com/mail/deeplink/read/{encoded_message_id}"
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:200] for item in value if isinstance(item, str)][:25]


def _allowed_review_actions(
    review: EmailReviewItemModel,
    artifact: EmailArtifactModel | None,
) -> list[str]:
    actions: list[str] = []
    assignable = bool(
        artifact
        and artifact.storage_key
        and artifact.detected_type in {"visa", "flight_ticket", "unknown"}
    )
    if assignable:
        actions.append("assign")
        if (
            artifact is not None
            and artifact.detected_type in {"visa", "flight_ticket"}
            and review.candidate_group_id
            and review.candidate_passenger_id
        ):
            actions.append("approve")
    if review.review_type == "processing_failure":
        actions.append("retry")
    actions.extend(["defer", "mark_unrelated", "reject"])
    return actions


def _display_conflicts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    responses: list[str] = []
    for item in value[:25]:
        if isinstance(item, dict) and "existing_document_id" in item:
            responses.append("An existing passenger document may be superseded.")
        elif isinstance(item, dict):
            responses.append("Conflicting deterministic evidence was found.")
    return responses


def _passport_number_hint(passenger: PassportSubmissionModel) -> str | None:
    fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    value = str(fields.get("passport_number") or "").strip()
    if not value:
        return None
    return f"••••{value[-4:]}" if len(value) > 4 else value


def _artifact_source_host(artifact: EmailArtifactModel) -> str | None:
    prefix = "Link from "
    if artifact.kind.endswith("link") and artifact.filename:
        if artifact.filename.startswith(prefix):
            return artifact.filename[len(prefix) :]
    return None


def _event_title(event: EmailActivityEventModel) -> str:
    return {
        "email_detected": "Email detected",
        "artifact_deduplicated": "Duplicate document skipped",
        "artifact_duplicate_reused": "Existing document assignment reused",
        "review_required": "Staff review required",
        "document_added": "Document added",
        "review_decision": "Review decision recorded",
        "ai_analysis_completed": "AI operational brief prepared",
        "ai_action_proposal_decided": "AI action decision recorded",
        "ai_deadline_decided": "AI deadline updated",
        "ai_reply_draft_decided": "Prepared reply decision recorded",
        "ai_reply_draft_edited": "Prepared reply edited",
        "ai_analysis_confirmed": "AI brief review confirmed",
        "ai_analysis_corrected": "AI brief correction recorded",
        "ai_analysis_dismissed": "AI brief dismissed",
    }.get(event.event_type, "Email workflow updated")


def _event_detail(event: EmailActivityEventModel) -> str | None:
    review_type = event.details.get("review_type")
    document_type = event.details.get("document_type")
    action = event.details.get("action")
    decision = event.details.get("decision")
    status_value = event.details.get("status")
    field_name = event.details.get("field_name")
    before_value = _bounded_event_value(event.details.get("before_value"))
    after_value = _bounded_event_value(event.details.get("after_value"))
    if isinstance(review_type, str):
        return f"Review reason: {review_type.replace('_', ' ')}."
    if isinstance(document_type, str):
        return f"Document type: {document_type.replace('_', ' ')}."
    if isinstance(action, str):
        return f"Action: {action.replace('_', ' ')}."
    if isinstance(decision, str):
        return f"Decision: {decision.replace('_', ' ')}."
    if isinstance(status_value, str):
        return f"Status: {status_value.replace('_', ' ')}."
    if isinstance(field_name, str):
        if (
            event.event_type == "ai_analysis_corrected"
            and before_value is not None
            and after_value is not None
        ):
            field_label = field_name.replace("_", " ")[:80]
            return f"Corrected field: {field_label}. Before: {before_value}. After: {after_value}."
        return f"Corrected field: {field_name.replace('_', ' ')}."
    return None


def _bounded_event_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) <= 240:
        return normalized
    return normalized[:239].rstrip() + "…"
