"""Agency, user and connection rollout overrides below the global kill switch."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.email_ai_models import _utcnow
from app.infrastructure.database.model_base import Base


class EmailAiRolloutPolicyModel(Base):
    """Optional agency/user/connection override below the global hard kill."""

    __module__ = "app.infrastructure.database.email_ai_models"

    __tablename__ = "email_ai_rollout_policies"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('agency', 'user', 'connection')",
            name="ck_email_ai_rollout_scope",
        ),
        CheckConstraint(
            "(scope_type = 'agency' AND owner_user_id IS NULL AND connection_id IS NULL) "
            "OR (scope_type = 'user' AND owner_user_id IS NOT NULL "
            "AND connection_id IS NULL) "
            "OR (scope_type = 'connection' AND owner_user_id IS NOT NULL "
            "AND connection_id IS NOT NULL)",
            name="ck_email_ai_rollout_shape",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id", "owner_user_id"],
            [
                "email_connections.id",
                "email_connections.agency_id",
                "email_connections.owner_user_id",
            ],
            name="fk_email_ai_rollout_connection_owner",
            ondelete="CASCADE",
        ),
        Index(
            "uq_email_ai_rollout_agency",
            "agency_id",
            unique=True,
            postgresql_where=text(
                "scope_type = 'agency' AND owner_user_id IS NULL AND connection_id IS NULL"
            ),
            sqlite_where=text(
                "scope_type = 'agency' AND owner_user_id IS NULL AND connection_id IS NULL"
            ),
        ),
        Index(
            "uq_email_ai_rollout_user",
            "agency_id",
            "owner_user_id",
            unique=True,
            postgresql_where=text(
                "scope_type = 'user' AND owner_user_id IS NOT NULL AND connection_id IS NULL"
            ),
            sqlite_where=text(
                "scope_type = 'user' AND owner_user_id IS NOT NULL AND connection_id IS NULL"
            ),
        ),
        Index(
            "uq_email_ai_rollout_connection",
            "connection_id",
            unique=True,
            postgresql_where=text("scope_type = 'connection' AND connection_id IS NOT NULL"),
            sqlite_where=text("scope_type = 'connection' AND connection_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
