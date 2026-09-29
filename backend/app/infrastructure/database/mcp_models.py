"""Durable MCP connection authority; no bearer credential is stored in plaintext."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class MCPControlModel(Base):
    __tablename__ = "mcp_control"
    __table_args__ = (CheckConstraint("id = 1", name="ck_mcp_control_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MCPGrantModel(Base):
    __tablename__ = "mcp_grants"
    __table_args__ = (
        CheckConstraint("security_version >= 1", name="ck_mcp_grant_security_version"),
        CheckConstraint("expires_at > created_at", name="ck_mcp_grant_expiry"),
        Index("ix_mcp_grants_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    client_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(120))
    resource: Mapped[str] = mapped_column(String(512))
    capabilities: Mapped[list[str]] = mapped_column(JSONB)
    security_version: Mapped[int] = mapped_column(Integer)
    mfa_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(64))


class MCPAuthorizationCodeModel(Base):
    __tablename__ = "mcp_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mcp_grants.id", ondelete="RESTRICT"))
    redirect_uri: Mapped[str] = mapped_column(String(1024))
    code_challenge: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MCPTokenModel(Base):
    __tablename__ = "mcp_tokens"
    __table_args__ = (
        CheckConstraint("kind IN ('access', 'refresh')", name="ck_mcp_token_kind"),
        Index("ix_mcp_tokens_grant_kind", "grant_id", "kind"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mcp_grants.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
