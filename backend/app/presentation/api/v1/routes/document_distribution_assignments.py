"""Stable assignment route composition and existing public imports."""

from __future__ import annotations

import uuid as uuid
from datetime import UTC as UTC
from datetime import datetime as datetime

from fastapi import (
    APIRouter as APIRouter,
)
from fastapi import (
    Depends as Depends,
)
from fastapi import (
    HTTPException as HTTPException,
)
from fastapi import (
    status as status,
)
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.mobile.passenger_change_propagation import (
    propagate_mobile_passenger_change as propagate_mobile_passenger_change,
)
from app.domain.entities.entities import User as User
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES as DOCUMENT_TYPES
from app.infrastructure.database.models import (
    DistributedDocumentModel as DistributedDocumentModel,
)
from app.infrastructure.database.models import (
    DocumentDistributionBatchModel as DocumentDistributionBatchModel,
)
from app.infrastructure.database.models import (
    DocumentWhatsAppDeliveryModel as DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.documents.document_approval_provenance import (
    preserve_document_type_approval as preserve_document_type_approval,
)
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job as process_storage_cleanup_job,
)
from app.infrastructure.documents.storage_cleanup import (
    stage_storage_cleanup_jobs as stage_storage_cleanup_jobs,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepository,
)
from app.presentation.api.v1.routes.document_distribution_assignment_delete import (
    delete_distribution_documents as delete_distribution_documents,
)
from app.presentation.api.v1.routes.document_distribution_assignment_delete import (
    router as _delete_distribution_documents_router,
)
from app.presentation.api.v1.routes.document_distribution_assignment_unassign import (
    router as _unassign_distribution_documents_router,
)
from app.presentation.api.v1.routes.document_distribution_assignment_unassign import (
    unassign_distribution_documents as unassign_distribution_documents,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents as _all_group_documents,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _latest_document_batch as _latest_document_batch,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _refresh_distribution_batches as _refresh_distribution_batches,
)
from app.presentation.api.v1.routes.document_distribution_responses import (
    _batch_response as _batch_response,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group as _get_authorized_group,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _group_passengers as _group_passengers,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES as DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    logger as logger,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _released_document_passenger_ids as _released_document_passenger_ids,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DeleteDistributionDocumentsRequest as DeleteDistributionDocumentsRequest,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentBatchResponse as DocumentBatchResponse,
)
from app.presentation.dependencies.auth import get_current_active_user as get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

router = APIRouter()
router.include_router(_unassign_distribution_documents_router)
router.include_router(_delete_distribution_documents_router)
