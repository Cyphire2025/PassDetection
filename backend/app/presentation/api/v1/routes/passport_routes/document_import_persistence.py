"""Apply staged staff documents under current authority and scoped target locks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import ClientGroup, User
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)

from .constants import _staff_code_for_submission
from .document_import_staging import DOCUMENT_IMAGE_ATTRIBUTES, PassportDocumentImportTarget


@dataclass(frozen=True)
class AppliedPassportDocumentImport:
    submissions: tuple[PassportSubmissionModel, ...]
    replaced_keys: tuple[str, ...]


async def apply_staged_document_import(
    session: AsyncSession,
    targets: Sequence[PassportDocumentImportTarget],
    *,
    actor: User,
    group: ClientGroup,
) -> AppliedPassportDocumentImport:
    rows = (
        await session.scalars(
            select(PassportSubmissionModel)
            .where(
                PassportSubmissionModel.id.in_({target.submission_id for target in targets}),
                PassportSubmissionModel.group_id == group.id,
                PassportSubmissionModel.agency_id == group.agency_id,
            )
            .order_by(PassportSubmissionModel.id)
            .with_for_update(of=PassportSubmissionModel)
            .execution_options(populate_existing=True),
        )
    ).all()
    by_id = {row.id: row for row in rows}
    crop_repo = PassportImageCropRepository(session)
    library_repo = PassportImageLibraryRepository(session)
    replaced_keys: list[str] = []
    replaced_crop_keys: list[str] = []
    applied: dict[uuid.UUID, PassportSubmissionModel] = {}
    for target in targets:
        item = target.item
        submission = by_id.get(target.submission_id)
        attr = DOCUMENT_IMAGE_ATTRIBUTES[item.document_type]
        if (
            submission is None
            or _staff_code_for_submission(submission) != item.staff_code
            or getattr(submission, attr) != target.original_storage_key
        ):
            raise HTTPException(
                409, "The passenger or image changed. Refresh the group and try again."
            )
        image_type = {
            "front": PassportImageType.PASSPORT_FRONT,
            "photo": PassportImageType.VISA_PHOTO,
            "back": PassportImageType.PASSPORT_BACK,
        }[item.document_type]
        old_key = target.original_storage_key
        setattr(submission, attr, target.storage_key)
        if old_key and old_key != target.storage_key:
            if not old_key.startswith("excel-imports/"):
                await library_repo.ensure_original(
                    submission_id=submission.id,
                    image_type=image_type,
                    storage_key=old_key,
                    created_at=submission.created_at,
                )
            _, old_crop_key, old_edit_key = await crop_repo.reset(
                submission_id=submission.id,
                image_type=image_type,
                updated_by_user_id=actor.id,
                expected_revision=None,
            )
            if old_crop_key:
                replaced_crop_keys.append(old_crop_key)
            if old_edit_key:
                replaced_crop_keys.append(old_edit_key)
        if old_key and not old_key.startswith("excel-imports/") and old_key != target.storage_key:
            replaced_keys.append(old_key)
        applied[submission.id] = submission
    return AppliedPassportDocumentImport(
        tuple(applied.values()), tuple(replaced_keys + replaced_crop_keys)
    )
