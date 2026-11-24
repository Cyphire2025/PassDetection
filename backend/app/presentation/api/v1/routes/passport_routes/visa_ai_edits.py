"""Stable visa ai edits API; focused owners retain route order."""

import asyncio as asyncio
import hashlib as hashlib
import uuid as uuid

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import File as File
from fastapi import Form as Form
from fastapi import HTTPException as HTTPException
from fastapi import Response as Response
from fastapi import UploadFile as UploadFile
from fastapi import status as status
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.core.config.settings import get_settings as get_settings
from app.core.security.passport_ai_edit_token import (
    PassportAiEditTokenError as PassportAiEditTokenError,
)
from app.core.security.passport_ai_edit_token import (
    issue_passport_ai_edit_token as issue_passport_ai_edit_token,
)
from app.core.security.passport_ai_edit_token import (
    verify_passport_ai_edit_token as verify_passport_ai_edit_token,
)
from app.domain.entities.entities import User as User
from app.domain.exceptions.exceptions import StorageError as StorageError
from app.domain.value_objects.passport_image_crop import PassportImageType as PassportImageType
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditError as GeminiVisaImageEditError,
)
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditService as GeminiVisaImageEditService,
)
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError as PassportImageCropError,
)
from app.infrastructure.imaging.passport_image_cropper import (
    render_passport_image_crop as render_passport_image_crop,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepository,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository as PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRevisionConflict as PassportImageCropRevisionConflict,
)
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository as PassportImageLibraryRepository,
)
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)
from app.presentation.api.v1.response_contracts import binary_responses as binary_responses
from app.presentation.api.v1.routes.passport_image_mutation import (
    lock_current_image_editor as lock_current_image_editor,
)
from app.presentation.api.v1.routes.passport_image_storage_write import (
    compensate_passport_image_failure as compensate_passport_image_failure,
)
from app.presentation.api.v1.routes.passport_image_storage_write import (
    write_passport_image_objects as write_passport_image_objects,
)
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _resolve_authorized_staff_passport_image as _resolve_authorized_staff_passport_image,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropCoordinates as PassportImageCropCoordinates,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResponse as PassportImageCropResponse,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportVisaAiPreviewRequest as PassportVisaAiPreviewRequest,
)
from app.presentation.dependencies.auth import get_current_active_user as get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

from .image_support import _crop_response as _crop_response
from .image_support import (
    _delete_crop_derivative_best_effort as _delete_crop_derivative_best_effort,
)
from .image_support import (
    _delete_ephemeral_edit_source_best_effort as _delete_ephemeral_edit_source_best_effort,
)
from .image_support import _visa_ai_input_storage_key as _visa_ai_input_storage_key
from .response_support import _effective_crop as _effective_crop
from .visa_ai_edits_apply import apply_visa_ai_image_edit as apply_visa_ai_image_edit
from .visa_ai_edits_apply import router as _apply_router
from .visa_ai_edits_preview import preview_visa_ai_image_edit as preview_visa_ai_image_edit
from .visa_ai_edits_preview import router as _preview_router
from .visa_ai_support import _visa_ai_edit_http_exception as _visa_ai_edit_http_exception

router = APIRouter()
router.include_router(_preview_router)
router.include_router(_apply_router)
