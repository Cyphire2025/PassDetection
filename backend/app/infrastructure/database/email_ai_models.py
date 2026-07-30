"""Owner-scoped persistence for the AI Travel Operations Inbox.

Structured results and decision provenance live here. Raw model prompts,
provider payloads, credentials, and unrestricted mailbox content do not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models import JSONB, Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class EmailAiRolloutPolicyModel(Base):
    """Optional agency/user/connection override below the global hard kill."""

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
                "scope_type = 'agency' AND owner_user_id IS NULL "
                "AND connection_id IS NULL"
            ),
            sqlite_where=text(
                "scope_type = 'agency' AND owner_user_id IS NULL "
                "AND connection_id IS NULL"
            ),
        ),
        Index(
            "uq_email_ai_rollout_user",
            "agency_id",
            "owner_user_id",
            unique=True,
            postgresql_where=text(
                "scope_type = 'user' AND owner_user_id IS NOT NULL "
                "AND connection_id IS NULL"
            ),
            sqlite_where=text(
                "scope_type = 'user' AND owner_user_id IS NOT NULL "
                "AND connection_id IS NULL"
            ),
        ),
        Index(
            "uq_email_ai_rollout_connection",
            "connection_id",
            unique=True,
            postgresql_where=text(
                "scope_type = 'connection' AND connection_id IS NOT NULL"
            ),
            sqlite_where=text(
                "scope_type = 'connection' AND connection_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
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
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
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


class EmailAiAnalysisModel(Base):
    __tablename__ = "email_ai_analyses"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "input_hash",
            "prompt_schema_version",
            name="uq_email_ai_analysis_input",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            "connection_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_ai_analysis_owner",
        ),
        ForeignKeyConstraint(
            ["message_id", "connection_id", "agency_id", "owner_user_id"],
            [
                "email_messages.id",
                "email_messages.connection_id",
                "email_messages.agency_id",
                "email_messages.owner_user_id",
            ],
            name="fk_email_ai_analysis_message_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', "
            "'review_required', 'failed', 'ignored')",
            name="ck_email_ai_analysis_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_ai_analysis_confidence",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_email_ai_analysis_attempts",
        ),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_email_ai_analysis_lease",
        ),
        Index(
            "ix_email_ai_analysis_owner_queue",
            "owner_user_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_email_ai_analysis_pending",
            "status",
            "lease_expires_at",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_provider: Mapped[str] = mapped_column(
        String(40), nullable=False, default="google", server_default="google"
    )
    ai_model: Mapped[str] = mapped_column(String(128), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_attention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    result_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    context_manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class EmailDetectedDeadlineModel(Base):
    __tablename__ = "email_detected_deadlines"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "source_fingerprint",
            name="uq_email_deadline_source",
        ),
        ForeignKeyConstraint(
            [
                "analysis_id",
                "message_id",
                "connection_id",
                "agency_id",
                "owner_user_id",
            ],
            [
                "email_ai_analyses.id",
                "email_ai_analyses.message_id",
                "email_ai_analyses.connection_id",
                "email_ai_analyses.agency_id",
                "email_ai_analyses.owner_user_id",
            ],
            name="fk_email_deadline_analysis_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('detected', 'review_required', 'acknowledged', "
            "'completed', 'dismissed')",
            name="ck_email_deadline_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_email_deadline_confidence",
        ),
        Index(
            "ix_email_deadline_owner_due",
            "owner_user_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deadline_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    is_ambiguous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="detected", server_default="detected"
    )
    resolution_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
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


class EmailActionProposalModel(Base):
    __tablename__ = "email_action_proposals"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_email_action_owner_key",
        ),
        ForeignKeyConstraint(
            [
                "analysis_id",
                "message_id",
                "connection_id",
                "agency_id",
                "owner_user_id",
            ],
            [
                "email_ai_analyses.id",
                "email_ai_analyses.message_id",
                "email_ai_analyses.connection_id",
                "email_ai_analyses.agency_id",
                "email_ai_analyses.owner_user_id",
            ],
            name="fk_email_action_analysis_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_email_action_risk",
        ),
        CheckConstraint(
            "status IN ('proposed', 'approval_required', 'approved', "
            "'rejected', 'dismissed', 'completed', 'failed', 'blocked')",
            name="ck_email_action_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_email_action_confidence",
        ),
        CheckConstraint("revision >= 1", name="ck_email_action_revision"),
        Index(
            "ix_email_action_owner_status",
            "owner_user_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    decision_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    execution_result: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
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


class EmailReplyDraftModel(Base):
    __tablename__ = "email_reply_drafts"
    __table_args__ = (
        UniqueConstraint("analysis_id", name="uq_email_reply_draft_analysis"),
        ForeignKeyConstraint(
            [
                "analysis_id",
                "message_id",
                "connection_id",
                "agency_id",
                "owner_user_id",
            ],
            [
                "email_ai_analyses.id",
                "email_ai_analyses.message_id",
                "email_ai_analyses.connection_id",
                "email_ai_analyses.agency_id",
                "email_ai_analyses.owner_user_id",
            ],
            name="fk_email_reply_analysis_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('prepared', 'edited', 'approved', 'dismissed')",
            name="ck_email_reply_draft_status",
        ),
        CheckConstraint("revision >= 1", name="ck_email_reply_draft_revision"),
        Index(
            "ix_email_reply_owner_status",
            "owner_user_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    recipients_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    subject: Mapped[str] = mapped_column(String(998), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="prepared", server_default="prepared"
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    edited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
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


class EmailAiFeedbackModel(Base):
    __tablename__ = "email_ai_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "analysis_id",
                "message_id",
                "connection_id",
                "agency_id",
                "owner_user_id",
            ],
            [
                "email_ai_analyses.id",
                "email_ai_analyses.message_id",
                "email_ai_analyses.connection_id",
                "email_ai_analyses.agency_id",
                "email_ai_analyses.owner_user_id",
            ],
            name="fk_email_feedback_analysis_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "feedback_type IN ('correction', 'confirmation', 'dismissal')",
            name="ck_email_feedback_type",
        ),
        Index(
            "ix_email_feedback_owner_created",
            "owner_user_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(24), nullable=False)
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    original_value: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    corrected_value: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
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
