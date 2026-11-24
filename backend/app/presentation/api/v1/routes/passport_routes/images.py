"""Stable images API; focused owners retain route order."""

import asyncio as asyncio
import hashlib as hashlib
import io as io
import mimetypes as mimetypes
import uuid as uuid
from typing import Annotated as Annotated

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import Header as Header
from fastapi import HTTPException as HTTPException
from fastapi import Query as Query
from fastapi import Response as Response
from fastapi import status as status
from fastapi.responses import StreamingResponse as StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.core.config.settings import get_settings as get_settings
from app.domain.entities.entities import User as User
from app.domain.exceptions.exceptions import StorageError as StorageError
from app.domain.value_objects.passport_image_crop import PassportImageType as PassportImageType
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError as PassportImageCropError,
)
from app.infrastructure.imaging.passport_image_cropper import (
    render_passport_image_crop as render_passport_image_crop,
)
from app.infrastructure.imaging.passport_image_cropper import (
    render_passport_image_thumbnail as render_passport_image_thumbnail,
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
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)
from app.presentation.api.v1.object_streaming import (
    private_object_streaming_response as private_object_streaming_response,
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
    PassportImageCropResetRequest as PassportImageCropResetRequest,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResponse as PassportImageCropResponse,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropUpdateRequest as PassportImageCropUpdateRequest,
)
from app.presentation.dependencies.auth import get_current_active_user as get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

from .image_support import _authorized_staff_passport_image as _authorized_staff_passport_image
from .image_support import _crop_response as _crop_response
from .image_support import _dashboard_thumbnail_cache as _dashboard_thumbnail_cache
from .image_support import (
    _delete_crop_derivative_best_effort as _delete_crop_derivative_best_effort,
)
from .image_support import (
    _delete_ephemeral_edit_source_best_effort as _delete_ephemeral_edit_source_best_effort,
)
from .image_support import _load_effective_passport_image as _load_effective_passport_image
from .images_crop import router as _crop_router
from .images_crop import update_passport_image_crop as update_passport_image_crop
from .images_reads import get_passport_image_crop as get_passport_image_crop
from .images_reads import get_passport_image_edit_source as get_passport_image_edit_source
from .images_reads import get_passport_image_original as get_passport_image_original
from .images_reads import get_passport_image_thumbnail as get_passport_image_thumbnail
from .images_reads import get_passport_image_view as get_passport_image_view
from .images_reads import router as _reads_router
from .images_reset import reset_passport_image_crop as reset_passport_image_crop
from .images_reset import router as _reset_router
from .response_support import _effective_crop as _effective_crop

router = APIRouter()
router.include_router(_reads_router)
router.include_router(_crop_router)
router.include_router(_reset_router)
