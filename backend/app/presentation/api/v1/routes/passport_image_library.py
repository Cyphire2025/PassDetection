"""Passport image-library router and explicit compatible workflow exports."""

from fastapi import APIRouter

from app.application.mobile.passenger_change_propagation import (
    propagate_mobile_passenger_change as propagate_mobile_passenger_change,
)
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase as ReextractPassportSubmissionUseCase,
)
from app.core.config.settings import (
    get_settings as get_settings,
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
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository as PassportImageLibraryRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository as PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)
from app.presentation.api.v1.routes.passport_image_library_manual import router as _manual_router
from app.presentation.api.v1.routes.passport_image_library_manual import (
    upload_passport_image_library_item as upload_passport_image_library_item,
)
from app.presentation.api.v1.routes.passport_image_library_reads import (
    _ensure_original_item as _ensure_original_item,
)
from app.presentation.api.v1.routes.passport_image_library_reads import (
    get_passport_image_library_item as get_passport_image_library_item,
)
from app.presentation.api.v1.routes.passport_image_library_reads import (
    list_passport_image_library as list_passport_image_library,
)
from app.presentation.api.v1.routes.passport_image_library_reads import router as _reads_router
from app.presentation.api.v1.routes.passport_image_library_responses import (
    _library_image_url as _library_image_url,
)
from app.presentation.api.v1.routes.passport_image_library_responses import (
    _library_item_response as _library_item_response,
)
from app.presentation.api.v1.routes.passport_image_library_selection import (
    router as _selection_router,
)
from app.presentation.api.v1.routes.passport_image_library_selection import (
    use_passport_image_library_item as use_passport_image_library_item,
)
from app.presentation.api.v1.routes.passport_image_mutation import (
    lock_passport_image_mutation as lock_passport_image_mutation,
)
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _authorized_staff_passport_image as _authorized_staff_passport_image,
)
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _crop_response as _crop_response,
)
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _resolve_authorized_staff_passport_image as _resolve_authorized_staff_passport_image,
)
from app.presentation.api.v1.routes.passport_routes.processing_support import (
    _dispatch_processing_job as _dispatch_processing_job,
)
from app.presentation.api.v1.routes.passports import (
    _validated_upload_file as _validated_upload_file,
)

router = APIRouter()
router.include_router(_reads_router)
router.include_router(_manual_router)
router.include_router(_selection_router)
