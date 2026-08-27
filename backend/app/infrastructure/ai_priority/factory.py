"""Default Redis coordinator factory.

Only the existing Redis URL is consumed here.  New limit settings are not read
until the settings/deployment checkpoint is explicitly resumed.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config.settings import get_settings
from app.infrastructure.ai_priority.config import AiPriorityConfig
from app.infrastructure.ai_priority.coordinator import AiPriorityCoordinator
from app.infrastructure.ai_priority.redis_store import RedisPriorityStore


@lru_cache
def get_ai_priority_coordinator() -> AiPriorityCoordinator:
    settings = get_settings()
    return AiPriorityCoordinator(
        store=RedisPriorityStore.from_url(settings.redis.broker_url),
        config=AiPriorityConfig(
            extraction_max_concurrency=(
                settings.gemini_extraction_max_concurrency
            ),
            verification_max_concurrency=(
                settings.gemini_verification_max_concurrency
            ),
            extraction_timeout_ms=settings.gemini_extraction_timeout_ms,
            verification_timeout_ms=int(settings.gemini_timeout_seconds * 1_000),
            extraction_quiet_period_ms=(
                settings.gemini_extraction_quiet_period_ms
            ),
            retry_max_attempts=settings.gemini_retry_max_attempts,
        ),
    )
