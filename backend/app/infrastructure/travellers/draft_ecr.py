"""Temporary back-page checks share the existing provider and global pacing."""
from redis.asyncio import Redis

from app.core.config.settings import get_settings
from app.domain.exceptions.resource_capacity import ImageProcessingBusy
from app.infrastructure.ai.gemini_ecr_service import EcrClassification, GeminiEcrService
from app.infrastructure.ecr.runtime import ProviderPacer, RateLimitUnavailable
from app.infrastructure.travellers.draft_extraction import DraftExtractionDeferred


async def check_draft_back(content: bytes, media: str) -> EcrClassification:
    settings = get_settings()
    redis = Redis.from_url(settings.redis.broker_url, socket_connect_timeout=3,
        socket_timeout=3, decode_responses=True)
    try:
        pacer = ProviderPacer(redis, settings.ecr_requests_per_minute)
        return await GeminiEcrService(settings=settings, before_attempt=pacer.acquire).classify(content, media)
    except (RateLimitUnavailable, ImageProcessingBusy) as error:
        raise DraftExtractionDeferred() from error
    finally:
        await redis.aclose()
