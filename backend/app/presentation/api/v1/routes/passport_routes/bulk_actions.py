"""Stable bulk passport API and explicit legacy compatibility exports."""

import uuid as uuid
from datetime import UTC as UTC
from datetime import datetime as datetime

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import HTTPException as HTTPException
from fastapi import Response as Response
from fastapi import status as status
from sqlalchemy import delete as delete
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.mobile.passenger_change_propagation import (
    propagate_mobile_passenger_change as propagate_mobile_passenger_change,
)
from app.application.security.access_level_actor import (
    actual_user_agency_id as actual_user_agency_id,
)
from app.application.security.access_level_actor import actual_user_role as actual_user_role
from app.application.security.access_level_actor import (
    refresh_access_level_actor as refresh_access_level_actor,
)
from app.application.security.access_level_actor import (
    revalidate_access_level_actor as revalidate_access_level_actor,
)
from app.application.security.authorization_policy import AuthorizationPolicy as AuthorizationPolicy
from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy as DestructiveMutationPolicy,
)
from app.application.security.destructive_mutation_policy import (
    record_destructive_failure as record_destructive_failure,
)
from app.core.logging.logger import get_logger as get_logger
from app.domain.entities.entities import GroupStatus as GroupStatus
from app.domain.entities.entities import PassportProcessingStatus as PassportProcessingStatus
from app.domain.entities.entities import StaffApprovalOutcome as StaffApprovalOutcome
from app.domain.entities.entities import User as User
from app.domain.entities.entities import UserRole as UserRole
from app.domain.exceptions.exceptions import AuthorizationError as AuthorizationError
from app.domain.exceptions.exceptions import ConflictError as ConflictError
from app.infrastructure.database.models import AuditLogModel as AuditLogModel
from app.infrastructure.database.models import ClientGroupModel as ClientGroupModel
from app.infrastructure.database.models import NotificationModel as NotificationModel
from app.infrastructure.database.models import (
    PassportRosterResolutionModel as PassportRosterResolutionModel,
)
from app.infrastructure.database.models import PassportSubmissionModel as PassportSubmissionModel
from app.infrastructure.database.models import UserModel as UserModel
from app.infrastructure.database.models import UserSecurityStateModel as UserSecurityStateModel
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job as process_storage_cleanup_job,
)
from app.infrastructure.documents.storage_cleanup import (
    stage_storage_cleanup_jobs as stage_storage_cleanup_jobs,
)
from app.infrastructure.observability.operational_events import OperationalEvent as OperationalEvent
from app.infrastructure.observability.operational_events import (
    record_operational_event as record_operational_event,
)
from app.infrastructure.qr.approved_passenger_qr_issuer import (
    ensure_approved_passenger_qrs as ensure_approved_passenger_qrs,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepository,
)
from app.infrastructure.repositories.client_group_repository import (
    ClientGroupRepository as ClientGroupRepository,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository as PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    lock_linked_whatsapp_broadcast_groups as lock_linked_whatsapp_broadcast_groups,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository as PassportSubmissionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository as UserRepository
from app.infrastructure.storage.passport_object_keys import (
    passport_storage_keys as passport_storage_keys,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked as PrivateDeliveryMutationBlocked,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    prepare_private_delivery_identity_mutation as prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.routes.passport_deletion_support import (
    previous_bulk_delete_result as previous_bulk_delete_result,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsRequest as BulkDeletePassportSubmissionsRequest,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsResponse as BulkDeletePassportSubmissionsResponse,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkStaffApprovePassportSubmissionsRequest as BulkStaffApprovePassportSubmissionsRequest,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkStaffApprovePassportSubmissionsResponse as BulkStaffApprovePassportSubmissionsResponse,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkStaffApproveSkippedSubmission as BulkStaffApproveSkippedSubmission,
)
from app.presentation.dependencies.auth import get_current_active_user as get_current_active_user
from app.presentation.dependencies.auth import require_recent_mfa as require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

from .bulk_actions_actor import _lock_active_bulk_approval_actor as _lock_active_bulk_approval_actor
from .bulk_actions_approval import (
    bulk_staff_approve_passport_submissions as bulk_staff_approve_passport_submissions,
)
from .bulk_actions_approval import router as _approval_router
from .bulk_actions_delete import (
    bulk_delete_passport_submissions as bulk_delete_passport_submissions,
)
from .bulk_actions_delete import router as _delete_router
from .bulk_actions_roster import (
    _active_roster_resolution_references as _active_roster_resolution_references,
)
from .bulk_actions_roster import logger as logger
from .bulk_actions_transitions import _apply_bulk_staff_approvals as _apply_bulk_staff_approvals
from .constants import (
    PASSPORT_DELETE_INLINE_CLEANUP_MAX_OBJECTS as PASSPORT_DELETE_INLINE_CLEANUP_MAX_OBJECTS,
)

router = APIRouter()
router.include_router(_delete_router)
router.include_router(_approval_router)
