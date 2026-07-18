"""Safe application helper for mandatory passport image verification."""

from __future__ import annotations

import asyncio
from typing import Any

from app.application.interfaces.passport_verification import IPassportVerificationService
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


async def verify_passport_fields(
    service: IPassportVerificationService | None,
    *,
    image_content: bytes,
    content_type: str,
    extracted_fields: dict[str, Any],
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Preserve OCR diagnostics while making verifier availability explicit to the caller."""

    original = dict(extracted_fields)
    if service is None:
        original["ai_verification"] = _unavailable_metadata("unavailable")
        return original
    if timeout_seconds is not None and timeout_seconds <= 0:
        original["ai_verification"] = _unavailable_metadata("deadline_exhausted")
        return original
    try:
        async def verify() -> Any:
            return await service.verify(
                image_content,
                content_type=content_type,
                extracted_fields=original,
                timeout_seconds=timeout_seconds,
            )

        if timeout_seconds is None:
            result = await verify()
        else:
            async with asyncio.timeout(timeout_seconds):
                result = await verify()
        merged = dict(result.merged_fields)
        merged["ai_verification"] = dict(result.metadata)
        return merged
    except TimeoutError:
        logger.warning("passport_ai_verification_deadline_exhausted")
        original["ai_verification"] = _unavailable_metadata("timeout")
        return original
    except Exception as exc:
        logger.error(
            "passport_ai_verification_unexpected_fallback",
            error_type=type(exc).__name__,
        )
        original["ai_verification"] = _unavailable_metadata("internal_error")
        return original


def _unavailable_metadata(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "available": False,
        "corrected_fields": [],
        "filled_fields": [],
    }
