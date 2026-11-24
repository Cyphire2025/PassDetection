"""Read-only daily counters for the super administrator's own account."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.assistant.contracts import AssistantError
from app.application.assistant.usage_contracts import AssistantUsageResponse
from app.core.assistant_usage import AssistantUsageLimits
from app.infrastructure.assistant.limits import _daily_key, _redis

OPERATIONS = {
    "voice_chats": "voice_chats",
    "typed_requests": "chat",
    "images": "images",
    "uploads": "uploads",
    "speech_requests": "speech",
}


async def usage_snapshot(user_id: UUID, limits: AssistantUsageLimits) -> AssistantUsageResponse:
    redis = _redis()
    now = datetime.now(UTC)
    try:
        values = await redis.mget(
            [_daily_key(user_id, operation, now) for operation in OPERATIONS.values()]
        )
        used = {
            name: max(0, int(value or 0)) for name, value in zip(OPERATIONS, values, strict=True)
        }
        return AssistantUsageResponse(
            observed_at=now,
            resets_at=(now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
            limits=limits,
            used=used,
        )
    except Exception:
        raise AssistantError(
            "usage_unavailable", "Current usage could not be loaded. Please try again."
        ) from None
    finally:
        await redis.aclose()
