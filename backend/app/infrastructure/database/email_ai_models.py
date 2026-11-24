"""Owner-scoped persistence for the AI Travel Operations Inbox.

Structured results and decision provenance live here. Raw model prompts,
provider payloads, credentials, and unrestricted mailbox content do not.
"""

from __future__ import annotations

import uuid as uuid
from datetime import UTC as UTC
from datetime import datetime as datetime

from sqlalchemy import Boolean as Boolean
from sqlalchemy import CheckConstraint as CheckConstraint
from sqlalchemy import DateTime as DateTime
from sqlalchemy import Float as Float
from sqlalchemy import ForeignKey as ForeignKey
from sqlalchemy import ForeignKeyConstraint as ForeignKeyConstraint
from sqlalchemy import Index as Index
from sqlalchemy import Integer as Integer
from sqlalchemy import String as String
from sqlalchemy import Text as Text
from sqlalchemy import UniqueConstraint as UniqueConstraint
from sqlalchemy import text as text
from sqlalchemy.dialects.postgresql import UUID as UUID
from sqlalchemy.orm import Mapped as Mapped
from sqlalchemy.orm import mapped_column as mapped_column

from app.infrastructure.database.model_base import JSONB as JSONB
from app.infrastructure.database.model_base import Base as Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


# Shared callbacks must exist before the original ordered table registration.
# isort: off
from ._email_ai_models.rollout import EmailAiRolloutPolicyModel as EmailAiRolloutPolicyModel  # noqa: E402
from ._email_ai_models.analyses import EmailAiAnalysisModel as EmailAiAnalysisModel  # noqa: E402
from ._email_ai_models.deadlines import EmailDetectedDeadlineModel as EmailDetectedDeadlineModel  # noqa: E402
from ._email_ai_models.proposals import EmailActionProposalModel as EmailActionProposalModel  # noqa: E402
from ._email_ai_models.drafts import EmailReplyDraftModel as EmailReplyDraftModel  # noqa: E402
from ._email_ai_models.feedback import EmailAiFeedbackModel as EmailAiFeedbackModel  # noqa: E402
# isort: on
