"""Short-lived, single-use OAuth and PKCE correlation state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.email_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class EmailOAuthStateModel(Base):
    """Single-use, short-lived OAuth correlation state.

    Only digests of browser-visible state and nonce values are retained. The
    PKCE verifier is encrypted and deferred just like provider tokens.
    """
    __module__ = "app.infrastructure.database.email_models"

    __tablename__ = "email_oauth_states"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_email_oauth_states_state_hash"),
        ForeignKeyConstraint(
            ["connection_id", "agency_id"],
            ["email_connections.id", "email_connections.agency_id"],
            name="fk_email_oauth_states_connection_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id", "user_id"],
            [
                "email_connections.id",
                "email_connections.agency_id",
                "email_connections.owner_user_id",
            ],
            name="fk_email_oauth_states_connection_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "provider IN ('gmail', 'outlook')",
            name="ck_email_oauth_states_provider",
        ),
        CheckConstraint(
            "length(state_hash) = 64",
            name="ck_email_oauth_states_state_hash",
        ),
        CheckConstraint(
            "nonce_hash IS NULL OR length(nonce_hash) = 64",
            name="ck_email_oauth_states_nonce_hash",
        ),
        CheckConstraint(
            "length(code_verifier_ciphertext) > 0",
            name="ck_email_oauth_states_verifier_nonempty",
        ),
        CheckConstraint(
            "key_version >= 1",
            name="ck_email_oauth_states_key_version",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_email_oauth_states_expiry",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="ck_email_oauth_states_consumed_at",
        ),
        CheckConstraint(
            "return_path IS NULL OR ("
            "substr(return_path, 1, 1) = '/' AND substr(return_path, 1, 2) != '//'"
            ")",
            name="ck_email_oauth_states_return_path",
        ),
        Index("ix_email_oauth_states_expiry", "expires_at", "consumed_at"),
        Index(
            "ix_email_oauth_states_agency_provider",
            "agency_id",
            "provider",
            "created_at",
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
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_verifier_ciphertext: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
        deferred=True,
    )
    key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    requested_scopes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    return_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
