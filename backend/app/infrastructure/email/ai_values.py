"""Pure persisted-state normalization for email AI claims and results."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailMessageModel


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _manual_retry_generation(analysis: EmailAiAnalysisModel) -> int:
    value = (getattr(analysis, "result_json", None) or {}).get(
        "manual_retry_generation",
        0,
    )
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _seed_input_hash(message: EmailMessageModel) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "message_id": str(message.id),
                "provider_message_id": message.provider_message_id,
                "updated_at": message.updated_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _safe_reply_address(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if (
        not 3 <= len(normalized) <= 320
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        return None
    local_part, domain = normalized.rsplit("@", 1)
    if not local_part or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return None
    return normalized


def _pause_loaded_analysis(
    analysis: EmailAiAnalysisModel,
    *,
    error_code: str,
) -> None:
    analysis.status = "pending"
    analysis.attempt_count = max(0, analysis.attempt_count - 1)
    analysis.last_error_code = error_code
    analysis.needs_attention = False
    analysis.lease_token = None
    analysis.lease_expires_at = None
    analysis.next_attempt_at = None
    analysis.started_at = None
    analysis.completed_at = None
