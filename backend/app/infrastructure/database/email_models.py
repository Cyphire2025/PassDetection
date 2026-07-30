"""Tenant-scoped persistence models for server-side email integrations.

The models deliberately store normalized metadata instead of full mailbox
contents. OAuth secrets and protected link material are encrypted before they
reach these columns and are deferred from normal ORM loads. Presentation
schemas must never expose ciphertext fields.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models import JSONB, Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class _ColumnDefaultContext(Protocol):
    def get_current_parameters(self) -> dict[str, object]: ...


def _normalized_email_default(context: _ColumnDefaultContext) -> str:
    value = context.get_current_parameters().get("email_address")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("email_address is required to normalize an email connection")
    return value.strip().lower()


class EmailConnectionModel(Base):
    """One provider mailbox connection owned by exactly one user and agency."""

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


class EmailOAuthStateModel(Base):
    """Single-use, short-lived OAuth correlation state.

    Only digests of browser-visible state and nonce values are retained. The
    PKCE verifier is encrypted and deferred just like provider tokens.
    """

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


class EmailMessageModel(Base):
    """A normalized provider message with minimal retained content."""

    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "provider_message_id",
            name="uq_email_messages_connection_provider_message",
        ),
        UniqueConstraint("id", "agency_id", name="uq_email_messages_id_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "owner_user_id",
            name="uq_email_messages_id_agency_owner",
        ),
        UniqueConstraint(
            "id",
            "connection_id",
            "agency_id",
            name="uq_email_messages_id_connection_agency",
        ),
        UniqueConstraint(
            "id",
            "connection_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_messages_id_connection_agency_owner",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id"],
            ["email_connections.id", "email_connections.agency_id"],
            name="fk_email_messages_connection_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id", "owner_user_id"],
            [
                "email_connections.id",
                "email_connections.agency_id",
                "email_connections.owner_user_id",
            ],
            name="fk_email_messages_connection_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "relevance_status IN ('pending', 'relevant', 'possible', 'ignored', 'failed')",
            name="ck_email_messages_relevance_status",
        ),
        CheckConstraint(
            "processing_status IN ("
            "'discovered', 'queued', 'processing', 'completed', "
            "'partially_completed', 'review_required', 'failed', 'ignored'"
            ")",
            name="ck_email_messages_processing_status",
        ),
        CheckConstraint(
            "relevance_confidence IS NULL OR "
            "(relevance_confidence >= 0 AND relevance_confidence <= 1)",
            name="ck_email_messages_relevance_confidence",
        ),
        CheckConstraint(
            "artifact_count >= 0 AND processed_artifact_count >= 0 AND review_count >= 0",
            name="ck_email_messages_counts",
        ),
        Index(
            "ix_email_messages_agency_received",
            "agency_id",
            "received_at",
        ),
        Index(
            "ix_email_messages_owner_received",
            "owner_user_id",
            "received_at",
        ),
        Index(
            "ix_email_messages_agency_processing",
            "agency_id",
            "processing_status",
            "received_at",
        ),
        Index(
            "ix_email_messages_connection_thread",
            "connection_id",
            "thread_id",
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
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider_history_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    internet_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    sender_address: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipients_json: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    has_attachments: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    relevance_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    relevance_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    processing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="discovered",
        server_default="discovered",
    )
    artifact_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    processed_artifact_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    review_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    ai_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class EmailArtifactModel(Base):
    """One independently retryable attachment or controlled-link artifact."""

    __tablename__ = "email_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "provider_artifact_id",
            name="uq_email_artifacts_message_provider_artifact",
        ),
        UniqueConstraint("id", "agency_id", name="uq_email_artifacts_id_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "owner_user_id",
            name="uq_email_artifacts_id_agency_owner",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            name="uq_email_artifacts_id_message_agency",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_artifacts_id_message_agency_owner",
        ),
        ForeignKeyConstraint(
            ["message_id", "agency_id"],
            ["email_messages.id", "email_messages.agency_id"],
            name="fk_email_artifacts_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id", "agency_id", "owner_user_id"],
            [
                "email_messages.id",
                "email_messages.agency_id",
                "email_messages.owner_user_id",
            ],
            name="fk_email_artifacts_message_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["duplicate_of_id", "agency_id"],
            ["email_artifacts.id", "email_artifacts.agency_id"],
            name="fk_email_artifacts_duplicate_agency",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["duplicate_of_id", "agency_id", "owner_user_id"],
            [
                "email_artifacts.id",
                "email_artifacts.agency_id",
                "email_artifacts.owner_user_id",
            ],
            name="fk_email_artifacts_duplicate_agency_owner",
            ondelete="NO ACTION",
        ),
        CheckConstraint(
            "kind IN ('attachment', 'inline', 'direct_link', 'cloud_link', 'portal_link')",
            name="ck_email_artifacts_source_kind",
        ),
        CheckConstraint(
            "retrieval_status IN ("
            "'pending', 'retrieving', 'retrieved', 'blocked', 'failed', 'ignored'"
            ")",
            name="ck_email_artifacts_retrieval_status",
        ),
        CheckConstraint(
            "processing_status IN ("
            "'pending', 'queued', 'processing', 'completed', 'review_required', "
            "'duplicate', 'failed', 'ignored'"
            ")",
            name="ck_email_artifacts_processing_status",
        ),
        CheckConstraint(
            "detected_type IN ('unknown', 'visa', 'flight_ticket', 'passport', 'other')",
            name="ck_email_artifacts_detected_type",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_email_artifacts_size",
        ),
        CheckConstraint(
            "sha256_digest IS NULL OR length(sha256_digest) = 64",
            name="ck_email_artifacts_sha256",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_email_artifacts_attempts",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_email_artifacts_lease_pair",
        ),
        CheckConstraint(
            "(source_url_ciphertext IS NULL) = (source_url_encryption_key_version IS NULL)",
            name="ck_email_artifacts_source_url_key_pair",
        ),
        CheckConstraint(
            "source_url_ciphertext IS NULL OR length(source_url_ciphertext) > 0",
            name="ck_email_artifacts_source_url_nonempty",
        ),
        CheckConstraint(
            "source_url_encryption_key_version IS NULL OR source_url_encryption_key_version >= 1",
            name="ck_email_artifacts_source_url_key_version",
        ),
        CheckConstraint(
            "duplicate_of_id IS NULL OR duplicate_of_id != id",
            name="ck_email_artifacts_not_self_duplicate",
        ),
        CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_email_artifacts_match_confidence",
        ),
        Index(
            "ix_email_artifacts_agency_processing",
            "agency_id",
            "processing_status",
            "created_at",
        ),
        Index(
            "ix_email_artifacts_owner_processing",
            "owner_user_id",
            "processing_status",
            "created_at",
        ),
        Index(
            "ix_email_artifacts_retry_due",
            "retrieval_status",
            "next_retry_at",
            "lease_expires_at",
        ),
        Index(
            "ix_email_artifacts_agency_sha256",
            "agency_id",
            "sha256_digest",
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
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_artifact_id: Mapped[str] = mapped_column(String(768), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_attachment_id: Mapped[str | None] = mapped_column(String(768), nullable=True)
    provider_part_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    declared_content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_url_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        deferred=True,
    )
    source_url_encryption_key_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    retrieval_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    processing_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    detected_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default="3",
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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


class EmailArtifactDocumentModel(Base):
    """Traceability link from an email artifact to the reused document pipeline."""

    __tablename__ = "email_artifact_documents"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "distributed_document_id",
            name="uq_email_artifact_documents_artifact_document",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "agency_id"],
            ["email_artifacts.id", "email_artifacts.agency_id"],
            name="fk_email_artifact_documents_artifact_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "agency_id", "owner_user_id"],
            [
                "email_artifacts.id",
                "email_artifacts.agency_id",
                "email_artifacts.owner_user_id",
            ],
            name="fk_email_artifact_documents_artifact_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "result_type IN ("
            "'created', 'existing_duplicate', 'revision_candidate', 'conflict_candidate'"
            ")",
            name="ck_email_artifact_documents_result_type",
        ),
        CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_email_artifact_documents_confidence",
        ),
        Index(
            "ix_email_artifact_documents_agency_document",
            "agency_id",
            "distributed_document_id",
        ),
        Index(
            "ix_email_artifact_documents_owner_document",
            "owner_user_id",
            "distributed_document_id",
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
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    distributed_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("distributed_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    result_type: Mapped[str] = mapped_column(String(32), nullable=False)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class EmailReviewItemModel(Base):
    """An exception requiring an explicit, revision-checked staff decision."""

    __tablename__ = "email_review_items"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="uq_email_review_items_id_agency"),
        UniqueConstraint(
            "id",
            "agency_id",
            "owner_user_id",
            name="uq_email_review_items_id_agency_owner",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            name="uq_email_review_items_id_message_agency",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_review_items_id_message_agency_owner",
        ),
        UniqueConstraint(
            "resolution_request_id",
            name="uq_email_review_items_resolution_request",
        ),
        ForeignKeyConstraint(
            ["message_id", "agency_id"],
            ["email_messages.id", "email_messages.agency_id"],
            name="fk_email_review_items_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id", "agency_id", "owner_user_id"],
            [
                "email_messages.id",
                "email_messages.agency_id",
                "email_messages.owner_user_id",
            ],
            name="fk_email_review_items_message_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
            ],
            name="fk_email_review_items_artifact_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id", "owner_user_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
                "email_artifacts.owner_user_id",
            ],
            name="fk_email_review_items_artifact_message_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "review_type IN ("
            "'relevance', 'retrieval', 'group_match', 'passenger_match', "
            "'document_conflict', 'possible_revision', 'traveller_replacement', "
            "'contact_change', 'processing_failure'"
            ")",
            name="ck_email_review_items_review_type",
        ),
        CheckConstraint(
            "status IN ('open', 'deferred', 'resolved', 'rejected', 'cancelled')",
            name="ck_email_review_items_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_review_items_confidence",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_email_review_items_revision",
        ),
        CheckConstraint(
            "(status IN ('resolved', 'rejected', 'cancelled') "
            "AND resolved_at IS NOT NULL) OR "
            "(status IN ('open', 'deferred') AND resolved_at IS NULL)",
            name="ck_email_review_items_resolution_state",
        ),
        CheckConstraint(
            "status != 'deferred' OR deferred_until IS NOT NULL",
            name="ck_email_review_items_deferred_until",
        ),
        Index(
            "uq_email_review_items_active_message",
            "agency_id",
            "message_id",
            "review_type",
            unique=True,
            postgresql_where=text("artifact_id IS NULL AND status IN ('open', 'deferred')"),
            sqlite_where=text("artifact_id IS NULL AND status IN ('open', 'deferred')"),
        ),
        Index(
            "uq_email_review_items_active_artifact",
            "agency_id",
            "artifact_id",
            "review_type",
            unique=True,
            postgresql_where=text("artifact_id IS NOT NULL AND status IN ('open', 'deferred')"),
            sqlite_where=text("artifact_id IS NOT NULL AND status IN ('open', 'deferred')"),
        ),
        Index(
            "ix_email_review_items_agency_queue",
            "agency_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_email_review_items_owner_queue",
            "owner_user_id",
            "status",
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
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    review_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="open",
        server_default="open",
    )
    proposed_action: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    conflicts: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    alternatives: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    proposed_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    candidate_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    resolution_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deferred_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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


class EmailActivityEventModel(Base):
    """Append-only, sanitized operational trace for one email workflow."""

    __tablename__ = "email_activity_events"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "event_key",
            name="uq_email_activity_events_agency_event_key",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id"],
            ["email_connections.id", "email_connections.agency_id"],
            name="fk_email_activity_events_connection_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["connection_id", "agency_id", "owner_user_id"],
            [
                "email_connections.id",
                "email_connections.agency_id",
                "email_connections.owner_user_id",
            ],
            name="fk_email_activity_events_connection_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id", "connection_id", "agency_id"],
            [
                "email_messages.id",
                "email_messages.connection_id",
                "email_messages.agency_id",
            ],
            name="fk_email_activity_events_message_connection_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id", "connection_id", "agency_id", "owner_user_id"],
            [
                "email_messages.id",
                "email_messages.connection_id",
                "email_messages.agency_id",
                "email_messages.owner_user_id",
            ],
            name="fk_email_activity_events_message_connection_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
            ],
            name="fk_email_activity_events_artifact_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id", "owner_user_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
                "email_artifacts.owner_user_id",
            ],
            name="fk_email_activity_events_artifact_message_agency_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["review_item_id", "message_id", "agency_id"],
            [
                "email_review_items.id",
                "email_review_items.message_id",
                "email_review_items.agency_id",
            ],
            name="fk_email_activity_events_review_message_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["review_item_id", "message_id", "agency_id", "owner_user_id"],
            [
                "email_review_items.id",
                "email_review_items.message_id",
                "email_review_items.agency_id",
                "email_review_items.owner_user_id",
            ],
            name="fk_email_activity_events_review_message_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "stage IN ('info', 'success', 'warning', 'failure')",
            name="ck_email_activity_events_stage",
        ),
        CheckConstraint(
            "actor_type IN ('system', 'user', 'provider')",
            name="ck_email_activity_events_actor_type",
        ),
        CheckConstraint(
            "actor_type = 'user' OR actor_user_id IS NULL",
            name="ck_email_activity_events_actor",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_activity_events_confidence",
        ),
        CheckConstraint(
            "artifact_id IS NULL OR message_id IS NOT NULL",
            name="ck_email_activity_events_artifact_message",
        ),
        CheckConstraint(
            "review_item_id IS NULL OR message_id IS NOT NULL",
            name="ck_email_activity_events_review_message",
        ),
        CheckConstraint(
            "ai_used OR (ai_provider IS NULL AND ai_model IS NULL)",
            name="ck_email_activity_events_ai_metadata",
        ),
        Index(
            "ix_email_activity_events_agency_occurred",
            "agency_id",
            "occurred_at",
        ),
        Index(
            "ix_email_activity_events_owner_occurred",
            "owner_user_id",
            "occurred_at",
        ),
        Index(
            "ix_email_activity_events_message_occurred",
            "message_id",
            "occurred_at",
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
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    review_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="system",
        server_default="system",
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary_code: Mapped[str] = mapped_column(String(100), nullable=False)
    # Sanitized structured metadata only: never raw message bodies, tokens, or URLs.
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    ai_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    ai_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    changed_entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    changed_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


def _reject_email_owner_change(_mapper: object, _connection: object, target: object) -> None:
    """Keep ownership immutable after an email row has been persisted."""

    owner_history = sa_inspect(target).attrs.owner_user_id.history
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
