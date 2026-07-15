"""Safe application helper for optional passport image verification."""

from __future__ import annotations

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
) -> dict[str, Any]:
    """Keep OCR usable even if an unexpected verifier implementation error escapes."""

    original = dict(extracted_fields)
    if service is None:
        return original
    try:
        result = await service.verify(
            image_content,
            content_type=content_type,
            extracted_fields=original,
        )
        return result.merged_fields
    except Exception as exc:
        logger.error(
            "passport_ai_verification_unexpected_fallback",
            error_type=type(exc).__name__,
        )
        original["ai_verification"] = {
            "status": "internal_error",
            "corrected_fields": [],
            "filled_fields": [],
        }
        return original
