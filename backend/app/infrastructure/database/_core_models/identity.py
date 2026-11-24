"""Agency, workforce identity and rotating dashboard refresh credentials."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.model_base import Base, _utcnow

if TYPE_CHECKING:
    from app.infrastructure.database._core_models.groups import ClientGroupModel


class AgencyModel(Base):
    __module__ = "app.infrastructure.database.models"
    __tablename__ = "agencies"
    __table_args__ = (
        UniqueConstraint("email", name="agencies_email_key"),
        Index("ix_agencies_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    users: Mapped[list[UserModel]] = relationship("UserModel", back_populates="agency")
    client_groups: Mapped[list[ClientGroupModel]] = relationship(
        "ClientGroupModel", back_populates="agency"
    )


class UserModel(Base):
    __module__ = "app.infrastructure.database.models"
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="users_email_key"),
        UniqueConstraint(
            "id",
            "agency_id",
            name="uq_users_id_agency",
        ),
        Index("ix_users_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum(
            "super_admin",
            "agency_admin",
            "agency_manager",
            "agency_staff",
            "agency_coordinator",
            "client_manager",
            name="user_role_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agency: Mapped[AgencyModel | None] = relationship("AgencyModel", back_populates="users")
    refresh_tokens: Mapped[list[RefreshTokenModel]] = relationship(
        "RefreshTokenModel", back_populates="user", cascade="all, delete-orphan"
    )


class RefreshTokenModel(Base):
    """
    Stores issued refresh tokens.

    Storing them in the DB allows:
      - Token revocation (logout, compromise response)
      - Rotation detection (detect replay attacks)
      - Audit trail of auth events
    """
    __module__ = "app.infrastructure.database.models"

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token", name="refresh_tokens_token_key"),
        Index("ix_refresh_tokens_token", "token"),
        ForeignKeyConstraint(
            ["session_id", "user_id"], ["dashboard_sessions.id", "dashboard_sessions.user_id"],
            name="fk_refresh_token_session_user", ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # Track which IP created this token for audit purposes
    created_from_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    authentication_methods: Mapped[str] = mapped_column(
        String(64), nullable=False, default="pwd", server_default="pwd"
    )
    mfa_authenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[UserModel] = relationship("UserModel", back_populates="refresh_tokens")
