"""Stable WhatsApp model aliases with original ORM registration order."""

from __future__ import annotations

import uuid as uuid
from datetime import (
    datetime as datetime,
)
from typing import (
    TYPE_CHECKING as TYPE_CHECKING,
)
from typing import (
    Any as Any,
)

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
    DateTime as DateTime,
)
from sqlalchemy import (
    ForeignKey as ForeignKey,
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
    text as text,
)
from sqlalchemy.dialects.postgresql import (
    UUID as UUID,
)
from sqlalchemy.orm import (
    Mapped as Mapped,
)
from sqlalchemy.orm import (
    mapped_column as mapped_column,
)
from sqlalchemy.orm import (
    relationship as relationship,
)

from app.infrastructure.database.model_base import (
    JSONB as JSONB,
)
from app.infrastructure.database.model_base import (
    Base as Base,
)
from app.infrastructure.database.model_base import (
    _utcnow as _utcnow,
)

# Keep the original class/table registration order and qualified ORM namespace.
# isort: off
from ._communications_models.broadcast import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from ._communications_models.source import (
    WhatsAppBroadcastSourceContactModel as WhatsAppBroadcastSourceContactModel,
    WhatsAppTravellerPhoneOverrideModel as WhatsAppTravellerPhoneOverrideModel,
    WhatsAppBroadcastRejectedContactModel as WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel as WhatsAppBroadcastSupportContactModel,
)
from ._communications_models.delivery import (
    WhatsAppMessageLogModel as WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel as WhatsAppRecipientMessageStateModel,
)
from ._communications_models.welcome import (
    WhatsAppPhoneWelcomeModel as WhatsAppPhoneWelcomeModel,
    WhatsAppPhoneWelcomeAttemptModel as WhatsAppPhoneWelcomeAttemptModel,
)
# isort: on
