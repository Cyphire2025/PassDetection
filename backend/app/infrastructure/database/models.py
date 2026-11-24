"""SQLAlchemy ORM models exposed through the stable database facade."""

from __future__ import annotations

import uuid as uuid
from datetime import date as date
from datetime import datetime as datetime
from typing import TYPE_CHECKING, TypedDict

from sqlalchemy import (
    BigInteger as BigInteger,
)
from sqlalchemy import (
    Boolean as Boolean,
)
from sqlalchemy import (
    CheckConstraint as CheckConstraint,
)
from sqlalchemy import (
    Date as Date,
)
from sqlalchemy import (
    DateTime as DateTime,
)
from sqlalchemy import (
    Enum as Enum,
)
from sqlalchemy import (
    Float as Float,
)
from sqlalchemy import (
    ForeignKey as ForeignKey,
)
from sqlalchemy import (
    ForeignKeyConstraint as ForeignKeyConstraint,
)
from sqlalchemy import (
    Index as Index,
)
from sqlalchemy import (
    Integer as Integer,
)
from sqlalchemy import (
    String as String,
)
from sqlalchemy import (
    Text as Text,
)
from sqlalchemy import (
    UniqueConstraint as UniqueConstraint,
)
from sqlalchemy import (
    literal_column as literal_column,
)
from sqlalchemy import (
    text as text,
)
from sqlalchemy.dialects.postgresql import UUID as UUID
from sqlalchemy.orm import Mapped as Mapped
from sqlalchemy.orm import mapped_column as mapped_column
from sqlalchemy.orm import relationship as relationship

from app.domain.value_objects.custom_questions import (
    CustomAnswerSnapshot as CustomAnswerSnapshot,
)
from app.domain.value_objects.custom_questions import (
    CustomDetailAnswerSnapshot as CustomDetailAnswerSnapshot,
)
from app.domain.value_objects.custom_questions import (
    CustomDetailDefinition as CustomDetailDefinition,
)
from app.domain.value_objects.custom_questions import (
    CustomQuestionDefinition as CustomQuestionDefinition,
)
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE as DEFAULT_TRIP_TIMEZONE
from app.infrastructure.database import communications_models as _communications_models
from app.infrastructure.database import (
    company_data_export_models as _company_data_export_models,  # noqa: F401
)
from app.infrastructure.database import (
    company_directory_queue as _company_directory_queue,  # noqa: F401
)
from app.infrastructure.database import document_models as _document_models
from app.infrastructure.database import identity_security_models as _identity_security_models
from app.infrastructure.database import operations_models as _operations_models
from app.infrastructure.database import (
    traveller_returning_draft_models as _traveller_returning_draft_models,  # noqa: F401
)
from app.infrastructure.database import (
    traveller_reuse_models as _traveller_reuse_models,  # noqa: F401
)
from app.infrastructure.database import whatsapp_receipt_models as _whatsapp_receipt_models
from app.infrastructure.database.dashboard_session_models import (
    DashboardSessionModel as DashboardSessionModel,
)
from app.infrastructure.database.model_base import JSONB as JSONB
from app.infrastructure.database.model_base import Base as Base
from app.infrastructure.database.model_base import _utcnow as _utcnow
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel as PublicUploadContactChallengeModel,
)
from app.infrastructure.database.search_index_sql import GROUP_SEARCH_SQL as GROUP_SEARCH_SQL
from app.infrastructure.database.search_index_sql import PASSPORT_SEARCH_SQL as PASSPORT_SEARCH_SQL
from app.infrastructure.database.travel_tracker_model import (
    TravelTrackerModel as TravelTrackerModel,
)

if TYPE_CHECKING:
    from app.infrastructure.database.gc_mobile_models import (
        ClientOrganizationModel as ClientOrganizationModel,
    )

WhatsAppBroadcastGroupModel = _communications_models.WhatsAppBroadcastGroupModel
WhatsAppBroadcastRecipientModel = _communications_models.WhatsAppBroadcastRecipientModel
WhatsAppBroadcastSourceContactModel = _communications_models.WhatsAppBroadcastSourceContactModel
WhatsAppTravellerPhoneOverrideModel = _communications_models.WhatsAppTravellerPhoneOverrideModel
WhatsAppBroadcastRejectedContactModel = _communications_models.WhatsAppBroadcastRejectedContactModel
WhatsAppBroadcastSupportContactModel = _communications_models.WhatsAppBroadcastSupportContactModel
WhatsAppMessageLogModel = _communications_models.WhatsAppMessageLogModel
WhatsAppRecipientMessageStateModel = _communications_models.WhatsAppRecipientMessageStateModel
WhatsAppPhoneWelcomeModel = _communications_models.WhatsAppPhoneWelcomeModel
WhatsAppPhoneWelcomeAttemptModel = _communications_models.WhatsAppPhoneWelcomeAttemptModel
WhatsAppProviderMessageBindingModel = _whatsapp_receipt_models.WhatsAppProviderMessageBindingModel
WhatsAppProviderReceiptModel = _whatsapp_receipt_models.WhatsAppProviderReceiptModel
DocumentDistributionBatchModel = _document_models.DocumentDistributionBatchModel
DistributedDocumentModel = _document_models.DistributedDocumentModel
DocumentWhatsAppDeliveryModel = _document_models.DocumentWhatsAppDeliveryModel
DocumentRenameBatchModel = _document_models.DocumentRenameBatchModel
DocumentRenameItemModel = _document_models.DocumentRenameItemModel
DocumentUploadChunkModel = _document_models.DocumentUploadChunkModel
StorageCleanupJobModel = _document_models.StorageCleanupJobModel
UntrustedUploadScanModel = _document_models.UntrustedUploadScanModel
DashboardAuthChallengeModel = _identity_security_models.DashboardAuthChallengeModel
IdentityActionTokenModel = _identity_security_models.IdentityActionTokenModel
IdentityNotificationOutboxModel = _identity_security_models.IdentityNotificationOutboxModel
MFARecoveryCodeModel = _identity_security_models.MFARecoveryCodeModel
UserSecurityStateModel = _identity_security_models.UserSecurityStateModel
AttendanceRecordModel = _operations_models.AttendanceRecordModel
AttendanceCloseoutCheckpointModel = _operations_models.AttendanceCloseoutCheckpointModel
AttendanceDiscardTombstoneModel = _operations_models.AttendanceDiscardTombstoneModel
AttendanceRuntimeRegistrationModel = _operations_models.AttendanceRuntimeRegistrationModel
AttendanceScanBatchModel = _operations_models.AttendanceScanBatchModel
AttendanceScanBatchResultModel = _operations_models.AttendanceScanBatchResultModel
AttendanceSessionRuntimeParticipantModel = (
    _operations_models.AttendanceSessionRuntimeParticipantModel
)
AttendanceSessionModel = _operations_models.AttendanceSessionModel
PassengerQRTokenModel = _operations_models.PassengerQRTokenModel
PassengerQrWhatsAppDeliveryModel = _operations_models.PassengerQrWhatsAppDeliveryModel
RoomingAssignmentModel = _operations_models.RoomingAssignmentModel
RoomingCheckinModel = _operations_models.RoomingCheckinModel
RoomingHotelModel = _operations_models.RoomingHotelModel
RoomingHotelPassengerModel = _operations_models.RoomingHotelPassengerModel
RoomingPassengerPreferenceModel = _operations_models.RoomingPassengerPreferenceModel
RoomingRoomModel = _operations_models.RoomingRoomModel


# Preserve declaration order and the legacy namespace used during ORM mapping.
# isort: off
from ._core_models.identity import AgencyModel as AgencyModel  # noqa: E402
from ._core_models.identity import UserModel as UserModel  # noqa: E402
from ._core_models.identity import RefreshTokenModel as RefreshTokenModel  # noqa: E402
from ._core_models.groups import ClientGroupModel as ClientGroupModel  # noqa: E402
from ._core_models.access import ManagerGroupAccessModel as ManagerGroupAccessModel  # noqa: E402
from ._core_models.access import CoordinatorAssignmentModel as CoordinatorAssignmentModel  # noqa: E402
from ._core_models.access import CoordinatorGroupAssignmentModel as CoordinatorGroupAssignmentModel  # noqa: E402
from ._core_models.passport import PassportSubmissionModel as PassportSubmissionModel  # noqa: E402
from ._core_models.exports import PassportExportHistoryModel as PassportExportHistoryModel  # noqa: E402
from ._core_models.roster import PassportRosterResolutionModel as PassportRosterResolutionModel  # noqa: E402
from ._core_models.images import PassportImageCropModel as PassportImageCropModel  # noqa: E402
from ._core_models.images import PassportVisaAiImageModel as PassportVisaAiImageModel  # noqa: E402
from ._core_models.images import PassportVisaAiImageJobModel as PassportVisaAiImageJobModel  # noqa: E402
from ._core_models.upload_workflow import QualifierSelectionModel as QualifierSelectionModel  # noqa: E402
from ._core_models.upload_workflow import PassportProcessingJobModel as PassportProcessingJobModel  # noqa: E402
from ._core_models.broadcast_links import ClientGroupWhatsAppBroadcastLinkModel as ClientGroupWhatsAppBroadcastLinkModel  # noqa: E402
from ._core_models.verification_jobs import PassportPostSubmissionVerificationJobModel as PassportPostSubmissionVerificationJobModel  # noqa: E402
from ._core_models.audit import AuditChainHeadModel as AuditChainHeadModel  # noqa: E402
from ._core_models.audit import AuditLogModel as AuditLogModel  # noqa: E402
from ._core_models.notifications import NotificationModel as NotificationModel  # noqa: E402


class PlatformSettingsValue(TypedDict, total=False):
    # Stored only under the separate whatsapp_template_names settings key.
    whatsapp_template_revision: int
    whatsapp_template_overrides: dict[str, str]
    platform_name: str
    require_client_email: bool
    require_client_phone: bool
    duplicate_contact_policy: str
    default_group_status: str
    auto_archive_closed_groups_days: int
    passport_data_retention_days: int
    mrz_review_threshold: float
    allow_manager_group_creation: bool
    audit_log_retention_days: int

from ._core_models.platform import PlatformSettingModel as PlatformSettingModel  # noqa: E402
# isort: on
