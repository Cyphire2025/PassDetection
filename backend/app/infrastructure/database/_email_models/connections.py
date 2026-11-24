"""Provider mailbox identity, encrypted grants, and synchronization state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.email_models import _normalized_email_default, _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class EmailConnectionModel(Base):
    """One provider mailbox connection owned by exactly one user and agency."""
    __module__ = "app.infrastructure.database.email_models"

    __tablename__ = "email_connections"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "agency_id",
            name="uq_email_connections_id_agency",
        ),
        UniqueConstraint(
            "id",
            "agency_id",
            "owner_user_id",
            name="uq_email_connections_id_agency_owner",
        ),
        UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_email_connections_provider_account",
        ),
        UniqueConstraint(
            "agency_id",
            "provider",
            "normalized_email_address",
            name="uq_email_connections_agency_provider_email",
        ),
        CheckConstraint(
            "provider IN ('gmail', 'outlook')",
            name="ck_email_connections_provider",
        ),
        CheckConstraint(
            "status IN ("
            "'pending', 'active', 'paused', 'expired', 'failing', "
            "'disconnecting', 'disconnected'"
            ")",
            name="ck_email_connections_status",
        ),
        CheckConstraint(
            "sync_state IN ('idle', 'queued', 'running', 'retry_wait', 'blocked')",
            name="ck_email_connections_sync_state",
        ),
        CheckConstraint(
            "token_key_version >= 1",
            name="ck_email_connections_key_version",
        ),
        CheckConstraint(
            "sync_generation >= 0",
            name="ck_email_connections_sync_generation",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_email_connections_failure_count",
        ),
        CheckConstraint(
            "(sync_lease_token IS NULL) = (sync_lease_expires_at IS NULL)",
            name="ck_email_connections_sync_lease_pair",
        ),
        CheckConstraint(
            "access_token_ciphertext IS NULL OR length(access_token_ciphertext) > 0",
            name="ck_email_connections_access_token_nonempty",
        ),
        CheckConstraint(
            "refresh_token_ciphertext IS NULL OR length(refresh_token_ciphertext) > 0",
            name="ck_email_connections_refresh_token_nonempty",
        ),
        CheckConstraint(
            "status != 'disconnected' OR disconnected_at IS NOT NULL",
            name="ck_email_connections_disconnected_at",
        ),
        CheckConstraint(
            "normalized_email_address = lower(trim(email_address))",
            name="ck_email_connections_normalized_email",
        ),
        Index(
            "ix_email_connections_agency_status",
            "agency_id",
            "status",
        ),
        Index(
            "ix_email_connections_owner_status",
            "owner_user_id",
            "status",
        ),
        Index(
            "ix_email_connections_sync_due",
            "status",
            "next_sync_at",
            "sync_lease_expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(512), nullable=False)
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_email_address: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        default=_normalized_email_default,
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    sync_state: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="idle",
        server_default="idle",
    )
    scopes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    ai_processing_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    ai_enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Ciphertext is deferred so ordinary connection queries cannot accidentally
    # serialize provider credentials.
    access_token_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        deferred=True,
    )
    refresh_token_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        deferred=True,
    )
    token_key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    watch_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    watch_expiration_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_sync_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_sync_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sync_lease_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sync_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sync_generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
