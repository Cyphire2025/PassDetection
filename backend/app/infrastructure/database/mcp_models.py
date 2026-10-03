"""Durable MCP connection authority; no bearer credential is stored in plaintext."""

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
    String,
    false,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class MCPControlModel(Base):
    __tablename__ = "mcp_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_mcp_control_singleton"),
        CheckConstraint("read_access_revision >= 1", name="ck_mcp_control_read_access_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    write_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    allowed_read_sections: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    allowed_write_sections: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    allowed_write_tools: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    read_access_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MCPGrantModel(Base):
    __tablename__ = "mcp_grants"
    __table_args__ = (
        CheckConstraint("security_version >= 1", name="ck_mcp_grant_security_version"),
        CheckConstraint("expires_at > created_at", name="ck_mcp_grant_expiry"),
        CheckConstraint("permission_revision >= 1", name="ck_mcp_grant_permission_revision"),
        CheckConstraint(
            "device_platform IS NULL OR device_platform IN ('Windows', 'macOS', 'Other')",
            name="ck_mcp_grant_device_platform",
        ),
        Index("ix_mcp_grants_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    client_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    read_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    write_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    allowed_read_sections: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    allowed_write_sections: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    permission_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    device_platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
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


class MCPConnectionRequestModel(Base):
    """Short-lived requester capability and immutable native OAuth binding."""

    __tablename__ = "mcp_connection_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','finalized')", name="ck_mcp_request_status"),
        CheckConstraint("expires_at > created_at", name="ck_mcp_request_expiry"),
        CheckConstraint("device_platform IN ('Windows','macOS','Other')", name="ck_mcp_request_platform"),
        CheckConstraint("security_version IS NULL OR security_version >= 1", name="ck_mcp_request_security_version"),
        Index("ix_mcp_requests_status_created", "status", "created_at"),
        Index("ix_mcp_requests_source_created", "source_hash", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    comparison_code: Mapped[str] = mapped_column(String(9))
    client_id: Mapped[str] = mapped_column(String(200))
    redirect_uri: Mapped[str] = mapped_column(String(1024))
    resource: Mapped[str] = mapped_column(String(512))
    oauth_state: Mapped[str] = mapped_column(String(512))
    code_challenge: Mapped[str] = mapped_column(String(43))
    requested_capabilities: Mapped[list[str]] = mapped_column(JSONB)
    approved_capabilities: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    read_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    write_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    allowed_read_sections: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    allowed_write_sections: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    name: Mapped[str] = mapped_column(String(120))
    device_platform: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    security_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mfa_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mcp_grants.id", ondelete="RESTRICT"), nullable=True, unique=True)
