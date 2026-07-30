"""Add personally owned email-integration records and an AI rollout switch.

Revision ID: 0065_ai_travel_inbox
Revises: 0064_document_resends

Ownership is backfilled only when the original creator still exists in the
same agency. Legacy connections that cannot be attributed safely are
disconnected, removed from dispatch, and stripped of provider credentials.
Their owner columns remain NULL so the migration never invents an owner.
Clean installations and installations without such legacy rows receive
database-level NOT NULL columns; otherwise the owner-readiness check and all
application queries fail closed until the orphan rows are deliberately
remediated.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0065_ai_travel_inbox"
down_revision = "0064_document_resends"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB(astext_type=sa.Text())
_OWNER_TABLES = (
    "email_connections",
    "email_messages",
    "email_artifacts",
    "email_artifact_documents",
    "email_review_items",
    "email_activity_events",
)


def upgrade() -> None:
    for table_name in _OWNER_TABLES:
        op.add_column(
            table_name,
            sa.Column("owner_user_id", _UUID, nullable=True),
        )
    op.add_column(
        "email_connections",
        sa.Column(
            "ai_processing_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "email_connections",
        sa.Column(
            "ai_enabled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "priority",
            sa.String(length=16),
            server_default="normal",
            nullable=False,
        ),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "category",
            sa.String(length=40),
            server_default="general",
            nullable=False,
        ),
    )
    op.add_column(
        "notifications",
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "metadata",
            _JSONB,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_notifications_user_dedupe_key",
        "notifications",
        ["user_id", "dedupe_key"],
    )
    op.create_index(
        "ix_notifications_priority",
        "notifications",
        ["priority"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_category",
        "notifications",
        ["category"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_unread_created",
        "notifications",
        ["user_id", "is_read", "created_at"],
        unique=False,
    )

    # A creator is accepted as the owner only when the user row still belongs
    # to the same agency. In particular, this deliberately does not assign old
    # platform-wide Super Admin connections to an arbitrary organization.
    op.execute(
        """
        UPDATE email_connections AS connections
        SET owner_user_id = connections.created_by_user_id
        FROM users AS owners
        WHERE owners.id = connections.created_by_user_id
          AND owners.agency_id = connections.agency_id
        """
    )
    op.execute(
        """
        UPDATE email_connections
        SET status = 'disconnected',
            sync_state = 'blocked',
            access_token_ciphertext = NULL,
            refresh_token_ciphertext = NULL,
            token_expires_at = NULL,
            sync_cursor = NULL,
            watch_resource_id = NULL,
            watch_expiration_at = NULL,
            sync_lease_token = NULL,
            sync_lease_expires_at = NULL,
            next_sync_at = NULL,
            ai_processing_enabled = false,
            ai_enabled_at = NULL,
            disconnected_at = COALESCE(disconnected_at, CURRENT_TIMESTAMP),
            last_error_code = 'EMAIL_OWNER_BACKFILL_REQUIRED',
            last_error_message = 'Reconnect this mailbox to establish its personal owner.',
            last_error_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE owner_user_id IS NULL
        """
    )

    op.execute(
        """
        UPDATE email_messages AS messages
        SET owner_user_id = connections.owner_user_id
        FROM email_connections AS connections
        WHERE messages.connection_id = connections.id
          AND messages.agency_id = connections.agency_id
        """
    )
    op.execute(
        """
        UPDATE email_artifacts AS artifacts
        SET owner_user_id = messages.owner_user_id
        FROM email_messages AS messages
        WHERE artifacts.message_id = messages.id
          AND artifacts.agency_id = messages.agency_id
        """
    )
    op.execute(
        """
        UPDATE email_artifact_documents AS links
        SET owner_user_id = artifacts.owner_user_id
        FROM email_artifacts AS artifacts
        WHERE links.artifact_id = artifacts.id
          AND links.agency_id = artifacts.agency_id
        """
    )
    op.execute(
        """
        UPDATE email_review_items AS reviews
        SET owner_user_id = messages.owner_user_id
        FROM email_messages AS messages
        WHERE reviews.message_id = messages.id
          AND reviews.agency_id = messages.agency_id
        """
    )
    op.execute(
        """
        UPDATE email_activity_events AS events
        SET owner_user_id = connections.owner_user_id
        FROM email_connections AS connections
        WHERE events.connection_id = connections.id
          AND events.agency_id = connections.agency_id
        """
    )

    op.create_check_constraint(
        "ck_email_connections_owner_ready",
        "email_connections",
        (
            "owner_user_id IS NOT NULL OR ("
            "status = 'disconnected' AND sync_state = 'blocked' "
            "AND access_token_ciphertext IS NULL "
            "AND refresh_token_ciphertext IS NULL "
            "AND sync_lease_token IS NULL "
            "AND sync_lease_expires_at IS NULL "
            "AND next_sync_at IS NULL "
            "AND ai_processing_enabled = false)"
        ),
    )
    op.create_foreign_key(
        "fk_email_connections_owner_user",
        "email_connections",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_unique_constraint(
        "uq_email_connections_id_agency_owner",
        "email_connections",
        ["id", "agency_id", "owner_user_id"],
    )
    op.create_unique_constraint(
        "uq_email_messages_id_agency_owner",
        "email_messages",
        ["id", "agency_id", "owner_user_id"],
    )
    op.create_unique_constraint(
        "uq_email_messages_id_connection_agency_owner",
        "email_messages",
        ["id", "connection_id", "agency_id", "owner_user_id"],
    )
    op.create_unique_constraint(
        "uq_email_artifacts_id_agency_owner",
        "email_artifacts",
        ["id", "agency_id", "owner_user_id"],
    )
    op.create_unique_constraint(
        "uq_email_artifacts_id_message_agency_owner",
        "email_artifacts",
        ["id", "message_id", "agency_id", "owner_user_id"],
    )
    op.create_unique_constraint(
        "uq_email_review_items_id_agency_owner",
        "email_review_items",
        ["id", "agency_id", "owner_user_id"],
    )
    op.create_unique_constraint(
        "uq_email_review_items_id_message_agency_owner",
        "email_review_items",
        ["id", "message_id", "agency_id", "owner_user_id"],
    )

    # OAuth state is deliberately short-lived. Discard stale states and any
    # reconnect state whose initiating user no longer matches the connection's
    # safely backfilled owner before enforcing the composite owner key.
    op.execute(
        """
        DELETE FROM email_oauth_states AS states
        WHERE states.consumed_at IS NOT NULL
           OR states.expires_at < CURRENT_TIMESTAMP
           OR (
                states.connection_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM email_connections AS connections
                    WHERE connections.id = states.connection_id
                      AND connections.agency_id = states.agency_id
                      AND connections.owner_user_id = states.user_id
                )
           )
        """
    )
    # Legacy attachment dedupe was agency-scoped. A cross-owner duplicate
    # pointer is only an optimization/provenance hint, so clear it rather than
    # inventing shared mailbox access or blocking the production migration.
    op.execute(
        """
        UPDATE email_artifacts AS artifacts
        SET duplicate_of_id = NULL
        WHERE artifacts.duplicate_of_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM email_artifacts AS original
              WHERE original.id = artifacts.duplicate_of_id
                AND original.agency_id = artifacts.agency_id
                AND original.owner_user_id = artifacts.owner_user_id
          )
        """
    )

    op.create_foreign_key(
        "fk_email_oauth_states_connection_agency_owner",
        "email_oauth_states",
        "email_connections",
        ["connection_id", "agency_id", "user_id"],
        ["id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_messages_connection_agency_owner",
        "email_messages",
        "email_connections",
        ["connection_id", "agency_id", "owner_user_id"],
        ["id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_artifacts_message_agency_owner",
        "email_artifacts",
        "email_messages",
        ["message_id", "agency_id", "owner_user_id"],
        ["id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_artifacts_duplicate_agency_owner",
        "email_artifacts",
        "email_artifacts",
        ["duplicate_of_id", "agency_id", "owner_user_id"],
        ["id", "agency_id", "owner_user_id"],
        ondelete="NO ACTION",
    )
    op.create_foreign_key(
        "fk_email_artifact_documents_artifact_agency_owner",
        "email_artifact_documents",
        "email_artifacts",
        ["artifact_id", "agency_id", "owner_user_id"],
        ["id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_review_items_message_agency_owner",
        "email_review_items",
        "email_messages",
        ["message_id", "agency_id", "owner_user_id"],
        ["id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_review_items_artifact_message_agency_owner",
        "email_review_items",
        "email_artifacts",
        ["artifact_id", "message_id", "agency_id", "owner_user_id"],
        ["id", "message_id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_activity_events_connection_agency_owner",
        "email_activity_events",
        "email_connections",
        ["connection_id", "agency_id", "owner_user_id"],
        ["id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_activity_events_message_connection_agency_owner",
        "email_activity_events",
        "email_messages",
        ["message_id", "connection_id", "agency_id", "owner_user_id"],
        ["id", "connection_id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_activity_events_artifact_message_agency_owner",
        "email_activity_events",
        "email_artifacts",
        ["artifact_id", "message_id", "agency_id", "owner_user_id"],
        ["id", "message_id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_email_activity_events_review_message_agency_owner",
        "email_activity_events",
        "email_review_items",
        ["review_item_id", "message_id", "agency_id", "owner_user_id"],
        ["id", "message_id", "agency_id", "owner_user_id"],
        ondelete="CASCADE",
    )

    op.create_index(
        "ix_email_connections_owner_status",
        "email_connections",
        ["owner_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_email_messages_owner_received",
        "email_messages",
        ["owner_user_id", "received_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_artifacts_owner_processing",
        "email_artifacts",
        ["owner_user_id", "processing_status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_artifact_documents_owner_document",
        "email_artifact_documents",
        ["owner_user_id", "distributed_document_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_review_items_owner_queue",
        "email_review_items",
        ["owner_user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_activity_events_owner_occurred",
        "email_activity_events",
        ["owner_user_id", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "email_ai_rollout_policies",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("owner_user_id", _UUID, nullable=True),
        sa.Column("connection_id", _UUID, nullable=True),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("updated_by_user_id", _UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope_type IN ('agency', 'user', 'connection')",
            name="ck_email_ai_rollout_scope",
        ),
        sa.CheckConstraint(
            "(scope_type = 'agency' AND owner_user_id IS NULL "
            "AND connection_id IS NULL) "
            "OR (scope_type = 'user' AND owner_user_id IS NOT NULL "
            "AND connection_id IS NULL) "
            "OR (scope_type = 'connection' AND owner_user_id IS NOT NULL "
            "AND connection_id IS NOT NULL)",
            name="ck_email_ai_rollout_shape",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "agency_id", "owner_user_id"],
            [
                "email_connections.id",
                "email_connections.agency_id",
                "email_connections.owner_user_id",
            ],
            name="fk_email_ai_rollout_connection_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    rollout_agency_where = sa.text(
        "scope_type = 'agency' AND owner_user_id IS NULL AND connection_id IS NULL"
    )
    rollout_user_where = sa.text(
        "scope_type = 'user' AND owner_user_id IS NOT NULL AND connection_id IS NULL"
    )
    rollout_connection_where = sa.text("scope_type = 'connection' AND connection_id IS NOT NULL")
    op.create_index(
        "uq_email_ai_rollout_agency",
        "email_ai_rollout_policies",
        ["agency_id"],
        unique=True,
        postgresql_where=rollout_agency_where,
        sqlite_where=rollout_agency_where,
    )
    op.create_index(
        "uq_email_ai_rollout_user",
        "email_ai_rollout_policies",
        ["agency_id", "owner_user_id"],
        unique=True,
        postgresql_where=rollout_user_where,
        sqlite_where=rollout_user_where,
    )
    op.create_index(
        "uq_email_ai_rollout_connection",
        "email_ai_rollout_policies",
        ["connection_id"],
        unique=True,
        postgresql_where=rollout_connection_where,
        sqlite_where=rollout_connection_where,
    )

    op.create_table(
        "email_ai_analyses",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("owner_user_id", _UUID, nullable=False),
        sa.Column("connection_id", _UUID, nullable=False),
        sa.Column("message_id", _UUID, nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "prompt_schema_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        sa.Column(
            "ai_provider",
            sa.String(length=40),
            server_default="google",
            nullable=False,
        ),
        sa.Column("ai_model", sa.String(length=128), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "needs_attention",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "result_json",
            _JSONB,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "context_manifest",
            _JSONB,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("lease_token", sa.String(length=128), nullable=True),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', "
            "'review_required', 'failed', 'ignored')",
            name="ck_email_ai_analysis_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_ai_analysis_confidence",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_email_ai_analysis_attempts",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_email_ai_analysis_lease",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "input_hash",
            "prompt_schema_version",
            name="uq_email_ai_analysis_input",
        ),
        sa.UniqueConstraint(
            "id",
            "message_id",
            "connection_id",
            "agency_id",
            "owner_user_id",
            name="uq_email_ai_analysis_owner",
        ),
    )
    op.create_index(
        "ix_email_ai_analysis_owner_queue",
        "email_ai_analyses",
        ["owner_user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_ai_analysis_pending",
        "email_ai_analyses",
        ["status", "lease_expires_at", "created_at"],
        unique=False,
    )

    op.create_table(
        "email_detected_deadlines",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("owner_user_id", _UUID, nullable=False),
        sa.Column("connection_id", _UUID, nullable=False),
        sa.Column("message_id", _UUID, nullable=False),
        sa.Column("analysis_id", _UUID, nullable=False),
        sa.Column("deadline_type", sa.String(length=40), nullable=False),
        sa.Column("source_phrase", sa.String(length=500), nullable=False),
        sa.Column(
            "source_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("source_timezone", sa.String(length=80), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "is_ambiguous",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="detected",
            nullable=False,
        ),
        sa.Column(
            "resolution_evidence",
            _JSONB,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('detected', 'review_required', 'acknowledged', 'completed', 'dismissed')",
            name="ck_email_deadline_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_email_deadline_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id",
            "source_fingerprint",
            name="uq_email_deadline_source",
        ),
    )
    op.create_index(
        "ix_email_deadline_owner_due",
        "email_detected_deadlines",
        ["owner_user_id", "status", "due_at"],
        unique=False,
    )

    op.create_table(
        "email_action_proposals",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("owner_user_id", _UUID, nullable=False),
        sa.Column("connection_id", _UUID, nullable=False),
        sa.Column("message_id", _UUID, nullable=False),
        sa.Column("analysis_id", _UUID, nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "payload_json",
            _JSONB,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("decision_by_user_id", _UUID, nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=1000), nullable=True),
        sa.Column(
            "execution_result",
            _JSONB,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_email_action_risk",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'approval_required', 'approved', "
            "'rejected', 'dismissed', 'completed', 'failed', 'blocked')",
            name="ck_email_action_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_email_action_confidence",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_email_action_revision",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_email_action_owner_key",
        ),
    )
    op.create_index(
        "ix_email_action_owner_status",
        "email_action_proposals",
        ["owner_user_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "email_reply_drafts",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("owner_user_id", _UUID, nullable=False),
        sa.Column("connection_id", _UUID, nullable=False),
        sa.Column("message_id", _UUID, nullable=False),
        sa.Column("analysis_id", _UUID, nullable=False),
        sa.Column(
            "recipients_json",
            _JSONB,
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="prepared",
            nullable=False,
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("edited_by_user_id", _UUID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'edited', 'approved', 'dismissed')",
            name="ck_email_reply_draft_status",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_email_reply_draft_revision",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id",
            name="uq_email_reply_draft_analysis",
        ),
    )
    op.create_index(
        "ix_email_reply_owner_status",
        "email_reply_drafts",
        ["owner_user_id", "status", "updated_at"],
        unique=False,
    )

    op.create_table(
        "email_ai_feedback",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("owner_user_id", _UUID, nullable=False),
        sa.Column("connection_id", _UUID, nullable=False),
        sa.Column("message_id", _UUID, nullable=False),
        sa.Column("analysis_id", _UUID, nullable=False),
        sa.Column("feedback_type", sa.String(length=24), nullable=False),
        sa.Column("field_name", sa.String(length=80), nullable=False),
        sa.Column(
            "original_value",
            _JSONB,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "corrected_value",
            _JSONB,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("created_by_user_id", _UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "feedback_type IN ('correction', 'confirmation', 'dismissal')",
            name="ck_email_feedback_type",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_feedback_owner_created",
        "email_ai_feedback",
        ["owner_user_id", "created_at"],
        unique=False,
    )

    # Enforce NOT NULL wherever the safe backfill was complete. If legacy
    # unattributed rows exist, the connection readiness check above keeps them
    # inert and all owner-scoped application queries exclude them.
    for table_name in _OWNER_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM {table_name} WHERE owner_user_id IS NULL
                ) THEN
                    ALTER TABLE {table_name}
                    ALTER COLUMN owner_user_id SET NOT NULL;
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    op.drop_index(
        "ix_email_feedback_owner_created",
        table_name="email_ai_feedback",
    )
    op.drop_table("email_ai_feedback")
    op.drop_index(
        "ix_email_reply_owner_status",
        table_name="email_reply_drafts",
    )
    op.drop_table("email_reply_drafts")
    op.drop_index(
        "ix_email_action_owner_status",
        table_name="email_action_proposals",
    )
    op.drop_table("email_action_proposals")
    op.drop_index(
        "ix_email_deadline_owner_due",
        table_name="email_detected_deadlines",
    )
    op.drop_table("email_detected_deadlines")
    op.drop_index(
        "ix_email_ai_analysis_pending",
        table_name="email_ai_analyses",
    )
    op.drop_index(
        "ix_email_ai_analysis_owner_queue",
        table_name="email_ai_analyses",
    )
    op.drop_table("email_ai_analyses")
    op.drop_index(
        "uq_email_ai_rollout_connection",
        table_name="email_ai_rollout_policies",
    )
    op.drop_index(
        "uq_email_ai_rollout_user",
        table_name="email_ai_rollout_policies",
    )
    op.drop_index(
        "uq_email_ai_rollout_agency",
        table_name="email_ai_rollout_policies",
    )
    op.drop_table("email_ai_rollout_policies")

    op.drop_index(
        "ix_email_activity_events_owner_occurred",
        table_name="email_activity_events",
    )
    op.drop_index(
        "ix_email_review_items_owner_queue",
        table_name="email_review_items",
    )
    op.drop_index(
        "ix_email_artifact_documents_owner_document",
        table_name="email_artifact_documents",
    )
    op.drop_index(
        "ix_email_artifacts_owner_processing",
        table_name="email_artifacts",
    )
    op.drop_index(
        "ix_email_messages_owner_received",
        table_name="email_messages",
    )
    op.drop_index(
        "ix_email_connections_owner_status",
        table_name="email_connections",
    )

    op.drop_constraint(
        "fk_email_activity_events_review_message_agency_owner",
        "email_activity_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_activity_events_artifact_message_agency_owner",
        "email_activity_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_activity_events_message_connection_agency_owner",
        "email_activity_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_activity_events_connection_agency_owner",
        "email_activity_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_review_items_artifact_message_agency_owner",
        "email_review_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_review_items_message_agency_owner",
        "email_review_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_artifact_documents_artifact_agency_owner",
        "email_artifact_documents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_artifacts_duplicate_agency_owner",
        "email_artifacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_artifacts_message_agency_owner",
        "email_artifacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_messages_connection_agency_owner",
        "email_messages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_email_oauth_states_connection_agency_owner",
        "email_oauth_states",
        type_="foreignkey",
    )

    op.drop_constraint(
        "uq_email_review_items_id_message_agency_owner",
        "email_review_items",
        type_="unique",
    )
    op.drop_constraint(
        "uq_email_review_items_id_agency_owner",
        "email_review_items",
        type_="unique",
    )
    op.drop_constraint(
        "uq_email_artifacts_id_message_agency_owner",
        "email_artifacts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_email_artifacts_id_agency_owner",
        "email_artifacts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_email_messages_id_connection_agency_owner",
        "email_messages",
        type_="unique",
    )
    op.drop_constraint(
        "uq_email_messages_id_agency_owner",
        "email_messages",
        type_="unique",
    )
    op.drop_constraint(
        "uq_email_connections_id_agency_owner",
        "email_connections",
        type_="unique",
    )
    op.drop_constraint(
        "fk_email_connections_owner_user",
        "email_connections",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_email_connections_owner_ready",
        "email_connections",
        type_="check",
    )

    op.drop_column("email_connections", "ai_enabled_at")
    op.drop_column("email_connections", "ai_processing_enabled")
    for table_name in reversed(_OWNER_TABLES):
        op.drop_column(table_name, "owner_user_id")

    op.drop_index(
        "ix_notifications_user_unread_created",
        table_name="notifications",
    )
    op.drop_index(
        "ix_notifications_category",
        table_name="notifications",
    )
    op.drop_index(
        "ix_notifications_priority",
        table_name="notifications",
    )
    op.drop_constraint(
        "uq_notifications_user_dedupe_key",
        "notifications",
        type_="unique",
    )
    op.drop_column("notifications", "metadata")
    op.drop_column("notifications", "dedupe_key")
    op.drop_column("notifications", "category")
    op.drop_column("notifications", "priority")
