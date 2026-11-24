"""Revocable refresh tokens belonging to device session families."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.gc_mobile_models import _utcnow
from app.infrastructure.database.model_base import Base


class MobileRefreshTokenModel(Base):
    """A single-use, hash-only refresh token in a rotation family."""

    __module__ = "app.infrastructure.database.gc_mobile_models"

    __tablename__ = "mobile_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mobile_refresh_token_hash"),
        UniqueConstraint(
            "session_id",
            "token_generation",
            name="uq_mobile_refresh_session_generation",
        ),
        UniqueConstraint(
            "id",
            "session_id",
            "agency_id",
            "family_id",
            name="uq_mobile_refresh_token_scope",
        ),
        ForeignKeyConstraint(
            ["session_id", "agency_id", "family_id"],
            [
                "mobile_device_sessions.id",
                "mobile_device_sessions.agency_id",
                "mobile_device_sessions.refresh_family_id",
            ],
            name="fk_mobile_refresh_session_family",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["parent_token_id", "session_id", "agency_id", "family_id"],
            [
                "mobile_refresh_tokens.id",
                "mobile_refresh_tokens.session_id",
                "mobile_refresh_tokens.agency_id",
                "mobile_refresh_tokens.family_id",
            ],
            name="fk_mobile_refresh_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(token_hash) = 64",
            name="ck_mobile_refresh_token_hash",
        ),
        CheckConstraint(
            "token_generation >= 1",
            name="ck_mobile_refresh_generation",
        ),
        CheckConstraint("expires_at > issued_at", name="ck_mobile_refresh_expiry"),
        CheckConstraint(
            "(revoked_at IS NULL AND revoke_reason IS NULL) OR revoked_at IS NOT NULL",
            name="ck_mobile_refresh_revocation_shape",
        ),
        CheckConstraint(
            "reuse_detected_at IS NULL OR revoked_at IS NOT NULL",
            name="ck_mobile_refresh_reuse_shape",
        ),
        Index(
            "ix_mobile_refresh_active",
            "session_id",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL AND revoked_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL AND revoked_at IS NULL"),
        ),
        Index("ix_mobile_refresh_family", "family_id", "token_generation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_token_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reuse_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
