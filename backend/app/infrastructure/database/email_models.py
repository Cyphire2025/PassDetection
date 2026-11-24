"""Tenant-scoped persistence models for server-side email integrations.

The models deliberately store normalized metadata instead of full mailbox
contents. OAuth secrets and protected link material are encrypted before they
reach these columns and are deferred from normal ORM loads. Presentation
schemas must never expose ciphertext fields.
"""

from __future__ import annotations

import uuid as uuid
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Protocol as Protocol

from sqlalchemy import BigInteger as BigInteger
from sqlalchemy import Boolean as Boolean
from sqlalchemy import CheckConstraint as CheckConstraint
from sqlalchemy import DateTime as DateTime
from sqlalchemy import Float as Float
from sqlalchemy import ForeignKey as ForeignKey
from sqlalchemy import ForeignKeyConstraint as ForeignKeyConstraint
from sqlalchemy import Index as Index
from sqlalchemy import Integer as Integer
from sqlalchemy import LargeBinary as LargeBinary
from sqlalchemy import String as String
from sqlalchemy import Text as Text
from sqlalchemy import UniqueConstraint as UniqueConstraint
from sqlalchemy import event as event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text as text
from sqlalchemy.dialects.postgresql import UUID as UUID
from sqlalchemy.orm import Mapped as Mapped
from sqlalchemy.orm import mapped_column as mapped_column

from app.infrastructure.database.model_base import JSONB as JSONB
from app.infrastructure.database.model_base import Base as Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class _ColumnDefaultContext(Protocol):
    def get_current_parameters(self) -> dict[str, object]: ...


def _normalized_email_default(context: _ColumnDefaultContext) -> str:
    value = context.get_current_parameters().get("email_address")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("email_address is required to normalize an email connection")
    return value.strip().lower()


# Registration order is published metadata; defaults must exist before owner imports.
# isort: off
from ._email_models.connections import EmailConnectionModel as EmailConnectionModel  # noqa: E402
from ._email_models.oauth import EmailOAuthStateModel as EmailOAuthStateModel  # noqa: E402
from ._email_models.messages import EmailMessageModel as EmailMessageModel  # noqa: E402
from ._email_models.artifacts import EmailArtifactModel as EmailArtifactModel  # noqa: E402
from ._email_models.documents import EmailArtifactDocumentModel as EmailArtifactDocumentModel  # noqa: E402
from ._email_models.reviews import EmailReviewItemModel as EmailReviewItemModel  # noqa: E402
from ._email_models.activity import EmailActivityEventModel as EmailActivityEventModel  # noqa: E402
# isort: on


def _reject_email_owner_change(_mapper: object, _connection: object, target: object) -> None:
    """Keep ownership immutable after an email row has been persisted."""

    inspection = sa_inspect(target)
    if inspection is None:
        raise ValueError("Email record inspection is unavailable")
    owner_history = inspection.attrs.owner_user_id.history
    if owner_history.has_changes() and owner_history.deleted:
        raise ValueError("Email record ownership cannot be changed")


for _owner_model in (
    EmailConnectionModel,
    EmailMessageModel,
    EmailArtifactModel,
    EmailArtifactDocumentModel,
    EmailReviewItemModel,
    EmailActivityEventModel,
):
    event.listen(_owner_model, "before_update", _reject_email_owner_change)
