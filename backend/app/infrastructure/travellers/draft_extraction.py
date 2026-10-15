"""Use the same admitted Gemini-first extraction as ordinary passport uploads."""
import asyncio
from typing import Any

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.application.use_cases.passports.passport_ai_verification import verify_passport_fields
from app.infrastructure.ai import GeminiPassportVerificationService
from app.infrastructure.ai_priority import MaintainPriorityLease, get_ai_priority_coordinator


class DraftExtractionDeferred(RuntimeError):
    pass


async def extract_draft_front(job_id: str, content: bytes, media: str) -> PassportExtractionResult:
    priority = get_ai_priority_coordinator()
    decision = await asyncio.to_thread(priority.try_start_extraction, job_id)
    if not decision.admitted:
        raise DraftExtractionDeferred()
    async with MaintainPriorityLease(priority, decision.lease):
        fields = await verify_passport_fields(GeminiPassportVerificationService(), image_content=content,
            content_type=media, extracted_fields={}, timeout_seconds=25)
    return PassportExtractionResult(extracted_fields=fields, overall_confidence=0, confidence_score={})


def draft_classification(fields: dict[str, Any]) -> dict[str, object]:
    raw = fields.get("ai_verification")
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if key in {"status", "available", "document_class", "page_type", "reason_code"}
        and isinstance(value, (str, bool, type(None))) and (not isinstance(value, str) or len(value) <= 160)}
