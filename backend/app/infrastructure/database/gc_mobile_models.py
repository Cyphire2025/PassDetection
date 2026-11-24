"""Persistence models for the native Group Companion application.

The mobile API is intentionally backed by explicit, tenant-scoped records
instead of reusing broad dashboard roles or serializing administrative ORM
objects.  Secrets stored here are hashes or application-encrypted bytes; raw
OTP codes, refresh tokens, push tokens, document URLs, and QR secrets do not
belong in these tables.
"""

from __future__ import annotations

import uuid as uuid
from datetime import UTC, datetime
from datetime import date as date

from sqlalchemy import BigInteger as BigInteger
from sqlalchemy import Boolean as Boolean
from sqlalchemy import CheckConstraint as CheckConstraint
from sqlalchemy import Date as Date
from sqlalchemy import DateTime as DateTime
from sqlalchemy import Float as Float
from sqlalchemy import ForeignKey as ForeignKey
from sqlalchemy import ForeignKeyConstraint as ForeignKeyConstraint
from sqlalchemy import Identity as Identity
from sqlalchemy import Index as Index
from sqlalchemy import Integer as Integer
from sqlalchemy import LargeBinary as LargeBinary
from sqlalchemy import String as String
from sqlalchemy import Text as Text
from sqlalchemy import UniqueConstraint as UniqueConstraint
from sqlalchemy import text as text
from sqlalchemy.dialects.postgresql import UUID as UUID
from sqlalchemy.orm import Mapped as Mapped
from sqlalchemy.orm import mapped_column as mapped_column

from app.infrastructure.database import (
    gc_notification_models as _gc_notification_models,  # noqa: F401
)
from app.infrastructure.database.model_base import JSONB as JSONB
from app.infrastructure.database.model_base import Base as Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


# Preserve original declaration order and construction-time ORM module identity.
# isort: off
from ._gc_models.organizations import ClientOrganizationModel as ClientOrganizationModel  # noqa: E402
from ._gc_models.organizations import ClientManagerProfileModel as ClientManagerProfileModel  # noqa: E402
from ._gc_models.group_access import GCGroupAccessModel as GCGroupAccessModel  # noqa: E402
from ._gc_models.group_access import (  # noqa: E402
    ClientManagerGroupAssignmentModel as ClientManagerGroupAssignmentModel,
)
from ._gc_models.common_documents import GCCommonDocumentModel as GCCommonDocumentModel  # noqa: E402
from ._gc_models.itineraries import GCItineraryVersionModel as GCItineraryVersionModel  # noqa: E402
from ._gc_models.itineraries import GCItineraryDayModel as GCItineraryDayModel  # noqa: E402
from ._gc_models.itineraries import GCItineraryItemModel as GCItineraryItemModel  # noqa: E402
from ._gc_models.announcements import GCAnnouncementModel as GCAnnouncementModel  # noqa: E402
from ._gc_models.passenger_identities import (  # noqa: E402
    MobilePassengerIdentityModel as MobilePassengerIdentityModel,
)
from ._gc_models.document_cache import (  # noqa: E402
    MobileDocumentMetadataCacheModel as MobileDocumentMetadataCacheModel,
)
from ._gc_models.otp_challenges import MobileOTPChallengeModel as MobileOTPChallengeModel  # noqa: E402
from ._gc_models.sessions import MobileDeviceSessionModel as MobileDeviceSessionModel  # noqa: E402
from ._gc_models.sessions import (  # noqa: E402
    MobilePassengerSessionIdentityModel as MobilePassengerSessionIdentityModel,
)
from ._gc_models.attestation import MobileAppAttestKeyModel as MobileAppAttestKeyModel  # noqa: E402
from ._gc_models.refresh_tokens import MobileRefreshTokenModel as MobileRefreshTokenModel  # noqa: E402
from ._gc_models.push_transport import MobilePushRegistrationModel as MobilePushRegistrationModel  # noqa: E402
from ._gc_models.push_transport import MobilePushDeliveryModel as MobilePushDeliveryModel  # noqa: E402
from ._gc_models.notifications import MobileNotificationModel as MobileNotificationModel  # noqa: E402
from ._gc_models.sync_changes import MobileSyncChangeModel as MobileSyncChangeModel  # noqa: E402
from ._gc_models.family_delegations import (  # noqa: E402
    PassengerFamilyDelegationModel as PassengerFamilyDelegationModel,
)
from ._gc_models.idempotency_receipts import (  # noqa: E402
    MobileIdempotencyReceiptModel as MobileIdempotencyReceiptModel,
)
from ._gc_models.incidents import MobileIncidentModel as MobileIncidentModel  # noqa: E402
# isort: on


__all__ = [
    "ClientManagerGroupAssignmentModel",
    "ClientManagerProfileModel",
    "ClientOrganizationModel",
    "GCAnnouncementModel",
    "GCCommonDocumentModel",
    "GCGroupAccessModel",
    "GCItineraryDayModel",
    "GCItineraryItemModel",
    "GCItineraryVersionModel",
    "MobileDeviceSessionModel",
    "MobileDocumentMetadataCacheModel",
    "MobileIdempotencyReceiptModel",
    "MobileIncidentModel",
    "MobileNotificationModel",
    "MobileOTPChallengeModel",
    "MobilePassengerIdentityModel",
    "MobilePassengerSessionIdentityModel",
    "MobilePushDeliveryModel",
    "MobilePushRegistrationModel",
    "MobileRefreshTokenModel",
    "MobileSyncChangeModel",
    "PassengerFamilyDelegationModel",
]
