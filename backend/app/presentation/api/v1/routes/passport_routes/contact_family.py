"""Bind family submission contacts to the submitted head's consumed proof."""

from __future__ import annotations

import hmac
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.public_contact_proof import digest as _digest
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, PassportSubmission
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)


async def require_verified_family_head(
    session: AsyncSession,
    *,
    submission: PassportSubmission,
    own_proof: PublicUploadContactChallengeModel,
    family_group_id: uuid.UUID | None,
    family_member_index: int | None,
    family_head_email: str | None,
    family_head_phone: str | None,
) -> None:
    """Bind family broadcast contacts to member zero's consumed OTP proof."""
    email = (family_head_email or "").lower().strip()
    phone = normalize_phone_number(family_head_phone)
    valid = False
    if family_group_id is not None and family_member_index == 0:
        valid = bool(
            email and phone == own_proof.phone_number
            and hmac.compare_digest(own_proof.email_hash, _digest("email", email))
        )
    elif family_group_id is not None and family_member_index is not None and family_member_index > 0:
        heads = (
            await session.execute(
                select(PassportSubmissionModel, PublicUploadContactChallengeModel)
                .join(
                    PublicUploadContactChallengeModel,
                    PublicUploadContactChallengeModel.submission_id == PassportSubmissionModel.id,
                )
                .where(
                    PassportSubmissionModel.agency_id == submission.agency_id,
                    PassportSubmissionModel.group_id == submission.group_id,
                    PassportSubmissionModel.family_group_id == family_group_id,
                    PassportSubmissionModel.submission_mode == "family",
                    PassportSubmissionModel.family_member_index == 0,
                    PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                    PublicUploadContactChallengeModel.group_id == submission.group_id,
                    PublicUploadContactChallengeModel.status == "consumed",
                    PublicUploadContactChallengeModel.consumed_at.is_not(None),
                )
                .limit(2)
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(heads) == 1:
            head, head_proof = heads[0]
            valid = bool(
                email and phone == head_proof.phone_number
                and normalize_phone_number(head.client_phone) == phone
                and (head.client_email or "").lower().strip() == email
                and hmac.compare_digest(head_proof.email_hash, _digest("email", email))
            )
    if not valid:
        raise HTTPException(
            400,
            detail={
                "code": "FAMILY_CONTACT_VERIFICATION_REQUIRED",
                "message": "Family contact details must match the verified first member. Submit that member first.",
                "field": "family_head_phone",
            },
            headers={"Cache-Control": "no-store"},
        )
