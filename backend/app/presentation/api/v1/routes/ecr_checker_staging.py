"""ECR attempt staging and locked acceptance, without database commits."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.ai.gemini_ecr_service import EcrImageValidationError, prepare_ecr_image
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService
from app.infrastructure.security.upload_validator import (
    DocumentIngestionDisabledError,
    MalwareScannerUnavailableError,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.ecr_checker_inputs import EcrUpload


@dataclass(slots=True)
class EcrUploadStaging:
    """Attempt-owned resources remain visible to cancellation/error cleanup."""

    stored_keys: list[str] = field(default_factory=list)
    items: list[EcrItemModel] = field(default_factory=list)
    commit_started: bool = False


async def stage_ecr_uploads(
    new_uploads: list[EcrUpload],
    *,
    agency_id: uuid.UUID,
    batch_id: uuid.UUID,
    current_user: User,
    limit: int,
    security: UploadSecurityService,
    storage: MinioStorageRepository,
    staging: EcrUploadStaging,
) -> None:
    for client_id, filename, content_type, digest, content in new_uploads:
        item = EcrItemModel(
            id=uuid.uuid4(),
            batch_id=batch_id,
            client_id=client_id,
            original_filename=filename,
            content_type=content_type,
            sha256=digest,
        )
        try:
            if content_type not in {
                "image/jpeg",
                "image/png",
                "image/webp",
                "application/octet-stream",
            }:
                raise ImageValidationError("Unsupported ECR image format")
            await security.validate_image(
                content=content,
                filename=filename,
                declared_content_type=content_type,
                context=UploadSecurityContext(
                    ingestion_flow="ecr_checker",
                    agency_id=current_user.agency_id,
                    user_id=current_user.id,
                ),
                max_bytes=limit,
                max_dimension=get_settings().ecr_image_max_dimension,
            )
            prepared = await asyncio.to_thread(prepare_ecr_image, content)
            key = f"ecr-checks/{agency_id}/{batch_id}/{item.id}.jpg"
            staging.stored_keys.append(key)
            await storage.upload_file(prepared, key, "image/jpeg")
            item.object_key, item.content_type = (key, "image/jpeg")
        except (DocumentIngestionDisabledError, MalwareScannerUnavailableError):
            raise HTTPException(
                503, "Image security scanning is unavailable; retry this upload"
            ) from None
        except (ImageValidationError, EcrImageValidationError):
            item.status, item.reason = ("failed", "invalid_image_upload")
        staging.items.append(item)


def accept_staged_ecr_items(
    session: AsyncSession,
    *,
    batch: EcrBatchModel,
    existing: dict[uuid.UUID, EcrItemModel],
    staging: EcrUploadStaging,
) -> None:
    accepted: list[EcrItemModel] = []
    for item in staging.items:
        existing_item = existing.get(item.client_id)
        if existing_item is None:
            accepted.append(item)
        elif (
            existing_item.sha256 != item.sha256
            or existing_item.original_filename != item.original_filename
        ):
            raise HTTPException(409, "An upload identifier was reused with different file content")
    if accepted:
        if batch.status != "uploading":
            raise HTTPException(
                409, "This batch has already started. Create a new batch to add files"
            )
        if len(existing) + len(accepted) > batch.expected_count:
            raise HTTPException(409, "This upload exceeds the batch's selected file count")
        session.add_all(accepted)
        batch.updated_at = datetime.now(UTC)
