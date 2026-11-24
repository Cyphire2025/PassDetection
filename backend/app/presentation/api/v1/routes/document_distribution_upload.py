"""Document distribution upload route and its unchanged public request contract."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.document_distribution_replacements import (
    MAX_FILENAME_REPLACEMENTS_LENGTH,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _with_staging_cleanup,
)
from app.presentation.api.v1.routes.document_distribution_upload_inputs import (
    validate_staging_receipt_batch as validate_staging_receipt_batch,
)
from app.presentation.api.v1.routes.document_distribution_upload_inputs import (
    validated_distribution_upload_inputs as validated_distribution_upload_inputs,
)
from app.presentation.api.v1.routes.document_distribution_upload_workflow import (
    run_distribution_upload,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentBatchResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/{document_type}/upload",
    response_model=DocumentBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
@_with_staging_cleanup
async def upload_documents(
    group_id: uuid.UUID,
    document_type: str,
    files: Annotated[list[UploadFile] | None, File()] = None,
    staging_receipts: Annotated[list[str] | None, Form()] = None,
    upload_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_index: Annotated[int | None, Form()] = None,
    expected_chunk_count: Annotated[int | None, Form()] = None,
    expected_file_count: Annotated[int | None, Form()] = None,
    filename_replacements: Annotated[
        str | None, Form(max_length=MAX_FILENAME_REPLACEMENTS_LENGTH)
    ] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    return await run_distribution_upload(
        group_id=group_id,
        document_type=document_type,
        files=files,
        staging_receipts=staging_receipts,
        upload_id=upload_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        expected_chunk_count=expected_chunk_count,
        expected_file_count=expected_file_count,
        filename_replacements=filename_replacements,
        current_user=current_user,
        session=session,
    )
