"""Load ECR verdicts only for authorized submissions in opted-in groups."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportSubmission


async def export_passport_ecr_results(
    session: AsyncSession,
    submissions: list[PassportSubmission],
    *,
    agency_id: uuid.UUID,
    group_details: dict[uuid.UUID, dict[str, Any]],
) -> dict[uuid.UUID, str]:
    # Export routes already authorize the supplied roster; the persistence
    # helper also scopes agency, current group setting and current back image.
    eligible = [
        submission for submission in submissions
        if group_details.get(submission.group_id, {}).get("passport_ecr_enabled")
    ]
    if not eligible:
        return {}
    from app.infrastructure.ecr.passport_runtime import passport_ecr_results

    return await passport_ecr_results(
        session, [item.id for item in eligible], agency_id=agency_id,
        expected_source_keys={item.id: item.passport_back_s3_key for item in eligible},
    )
