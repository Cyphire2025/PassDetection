"""ECR API composition and its original compatibility exports."""

from __future__ import annotations

# Original imported objects remain available to existing internal callers.
# ruff: noqa: F401
import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.security.access_level_actor import (
    actual_user_agency_id,
    actual_user_role,
    refresh_access_level_actor,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError, ImageValidationError
from app.infrastructure.ai.gemini_ecr_service import EcrImageValidationError, prepare_ecr_image
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import AgencyModel, UserModel, UserSecurityStateModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.ecr_excel_exporter import build_ecr_workbook
from app.infrastructure.repositories.ecr_read_repository import (
    ECR_ALLOWED_ROLES,
    ECR_COUNT_FIELDS,
    ecr_item_counts,
    ecr_scope,
)
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService
from app.infrastructure.security.upload_validator import (
    DocumentIngestionDisabledError,
    MalwareScannerUnavailableError,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.response_contracts import XLSX, binary_responses
from app.presentation.api.v1.routes.ecr_checker_actions import (
    _dispatch,
    export_ecr_batch,
    retry_ecr_batch,
    start_ecr_batch,
)
from app.presentation.api.v1.routes.ecr_checker_actions import router as _actions_router
from app.presentation.api.v1.routes.ecr_checker_batches import (
    create_ecr_batch,
    get_ecr_batch,
    list_ecr_batches,
)
from app.presentation.api.v1.routes.ecr_checker_batches import router as _batches_router
from app.presentation.api.v1.routes.ecr_checker_inputs import (
    _UPLOAD_GATES,
    _parse_client_ids,
    _run_admitted_upload,
)
from app.presentation.api.v1.routes.ecr_checker_support import (
    _ALLOWED_ROLES,
    _MUTATION,
    SessionDep,
    UserDep,
    _batch,
    _items,
    _lock_active_actor,
    _response,
    _scope,
    _summary,
    logger,
)
from app.presentation.api.v1.routes.ecr_checker_upload import (
    _upload_ecr_items_admitted,
    upload_ecr_items,
)
from app.presentation.api.v1.routes.ecr_checker_upload import router as _upload_router
from app.presentation.api.v1.schemas.ecr_schemas import (
    CreateEcrBatch,
    EcrBatchResponse,
    EcrBatchSummary,
    EcrItemResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

# Preserve public module/qualname and pickle lookups; source inspection resolves
# each actual owner instead of a facade proxy.
for _ecr_function in (
    _scope,
    _lock_active_actor,
    _batch,
    _items,
    _summary,
    _response,
    _run_admitted_upload,
    _parse_client_ids,
    create_ecr_batch,
    list_ecr_batches,
    get_ecr_batch,
    upload_ecr_items,
    _upload_ecr_items_admitted,
    _dispatch,
    start_ecr_batch,
    retry_ecr_batch,
    export_ecr_batch,
):
    _ecr_function.__module__ = __name__
del _ecr_function

router = APIRouter()
router.include_router(_batches_router)
router.include_router(_upload_router)
router.include_router(_actions_router)
