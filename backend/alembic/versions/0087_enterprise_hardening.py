"""Add enterprise attendance, identity, upload, and audit foundations.

Revision ID: 0087_enterprise_hardening
Revises: 0085_platform_retention_controls

This is intentionally a sibling of the separately reserved 0086 My Photos
revision.  An integration branch must add an explicit merge revision after
both feature branches are combined.

Existing closeout rows remain as nullable-runtime legacy account checkpoints.
New clients use runtime registrations; a partial unique index preserves the
old one-row-per-account behavior for request bodies without a runtime.

Audit rows created before this revision remain version 0 and visibly
unchained. New application writes use version 1. The append-only trigger does
not make PostgreSQL an external immutable/WORM sink; it prevents ordinary
application UPDATE/DELETE statements and makes tampering detectable.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0087_enterprise_hardening"
down_revision = "0085_platform_retention_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite tenant keys make cross-tenant runtime links impossible at the
    # database layer, not merely unlikely because a route filtered correctly.
    op.create_unique_constraint("uq_users_id_agency", "users", ["id", "agency_id"])
    op.create_unique_constraint(
        "uq_client_groups_id_agency",
        "client_groups",
        ["id", "agency_id"],
    )

    op.add_column(
        "attendance_sessions",
        sa.Column("scheduled_starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attendance_sessions",
        sa.Column("scheduled_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attendance_sessions",
        sa.Column("schedule_timezone", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "attendance_sessions",
        sa.Column("schedule_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_unique_constraint(
        "uq_attendance_sessions_id_agency",
        "attendance_sessions",
        ["id", "agency_id"],
    )
    op.create_unique_constraint(
        "uq_attendance_sessions_id_agency_group",
        "attendance_sessions",
        ["id", "agency_id", "group_id"],
    )
    op.create_check_constraint(
        "ck_attendance_sessions_scheduled_window",
        "attendance_sessions",
        "(scheduled_starts_at IS NULL AND scheduled_ends_at IS NULL) OR "
        "(scheduled_starts_at IS NOT NULL AND scheduled_ends_at IS NOT NULL "
        "AND scheduled_ends_at > scheduled_starts_at)",
    )
    op.create_check_constraint(
        "ck_attendance_sessions_schedule_version",
        "attendance_sessions",
        "schedule_version >= 1",
    )
    op.create_check_constraint(
        "ck_attendance_sessions_schedule_timezone",
        "attendance_sessions",
        "schedule_timezone IS NULL OR "
        "(length(schedule_timezone) BETWEEN 1 AND 64 "
        "AND schedule_timezone = trim(schedule_timezone))",
    )
    op.create_index(
        "ix_attendance_sessions_group_schedule",
        "attendance_sessions",
        ["group_id", "scheduled_starts_at", "scheduled_ends_at"],
    )

    op.create_table(
        "attendance_runtime_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coordinator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_kind", sa.String(length=24), nullable=False),
        sa.Column("runtime_identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("native_mobile_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=80), nullable=True),
        sa.Column("replaced_by_runtime_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "runtime_kind IN ('native_mobile', 'pwa', 'webview', 'legacy_account')",
            name="ck_attendance_runtime_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'expired', 'lost', 'replaced')",
            name="ck_attendance_runtime_status",
        ),
        sa.CheckConstraint(
            "length(runtime_identifier_hash) = 64",
            name="ck_attendance_runtime_identifier_hash",
        ),
        sa.CheckConstraint(
            "expires_at > registered_at",
            name="ck_attendance_runtime_expiry",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR "
            "(status <> 'active' AND revoked_at IS NOT NULL)",
            name="ck_attendance_runtime_revocation_shape",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["coordinator_user_id", "agency_id"],
            ["users.id", "users.agency_id"],
            name="fk_attendance_runtime_coordinator_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["native_mobile_session_id"],
            ["mobile_device_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_runtime_id"],
            ["attendance_runtime_registrations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "agency_id",
            "coordinator_user_id",
            name="uq_attendance_runtime_id_tenant_coordinator",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "coordinator_user_id",
            "runtime_identifier_hash",
            name="uq_attendance_runtime_identifier",
        ),
    )
    op.create_index(
        "ix_attendance_runtime_coordinator_status",
        "attendance_runtime_registrations",
        ["agency_id", "coordinator_user_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_attendance_runtime_native_session",
        "attendance_runtime_registrations",
        ["native_mobile_session_id"],
    )

    op.create_table(
        "attendance_session_runtime_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coordinator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_registration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participation_source", sa.String(length=16), nullable=False),
        sa.Column("first_participated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_participated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "participation_source IN ('scan', 'checkpoint', 'discard', 'legacy')",
            name="ck_attendance_participant_source",
        ),
        sa.CheckConstraint(
            "last_participated_at >= first_participated_at",
            name="ck_attendance_participant_time_order",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["attendance_sessions.id", "attendance_sessions.agency_id"],
            name="fk_attendance_participant_session_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_participant_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "runtime_registration_id",
            name="uq_attendance_session_runtime_participant",
        ),
    )
    op.create_index(
        "ix_attendance_participants_session_coordinator",
        "attendance_session_runtime_participants",
        ["session_id", "coordinator_user_id"],
    )

    op.add_column(
        "attendance_closeout_checkpoints",
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "attendance_closeout_checkpoints",
        sa.Column("runtime_registration_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE attendance_closeout_checkpoints AS checkpoint
           SET agency_id = attendance_session.agency_id
          FROM attendance_sessions AS attendance_session
         WHERE attendance_session.id = checkpoint.session_id
           AND checkpoint.agency_id IS NULL
        """
    )
    op.alter_column(
        "attendance_closeout_checkpoints",
        "agency_id",
        nullable=False,
    )
    op.drop_constraint(
        "uq_attendance_closeout_checkpoint_coordinator",
        "attendance_closeout_checkpoints",
        type_="unique",
    )
    op.create_foreign_key(
        "fk_attendance_closeout_agency",
        "attendance_closeout_checkpoints",
        "agencies",
        ["agency_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_attendance_closeout_runtime",
        "attendance_closeout_checkpoints",
        "attendance_runtime_registrations",
        ["runtime_registration_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_attendance_closeout_session_tenant",
        "attendance_closeout_checkpoints",
        "attendance_sessions",
        ["session_id", "agency_id"],
        ["id", "agency_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_attendance_closeout_runtime_tenant_coordinator",
        "attendance_closeout_checkpoints",
        "attendance_runtime_registrations",
        ["runtime_registration_id", "agency_id", "coordinator_user_id"],
        ["id", "agency_id", "coordinator_user_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_attendance_closeout_checkpoint_runtime",
        "attendance_closeout_checkpoints",
        ["session_id", "coordinator_user_id", "runtime_registration_id"],
    )
    op.create_index(
        "uq_attendance_closeout_legacy_account",
        "attendance_closeout_checkpoints",
        ["session_id", "coordinator_user_id"],
        unique=True,
        postgresql_where=sa.text("runtime_registration_id IS NULL"),
    )

    op.add_column(
        "attendance_records",
        sa.Column("runtime_registration_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_attendance_record_runtime",
        "attendance_records",
        "attendance_runtime_registrations",
        ["runtime_registration_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_attendance_record_runtime_tenant_coordinator",
        "attendance_records",
        "attendance_runtime_registrations",
        ["runtime_registration_id", "agency_id", "coordinator_user_id"],
        ["id", "agency_id", "coordinator_user_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "attendance_scan_batches",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coordinator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_registration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_attendance_scan_batch_fingerprint",
        ),
        sa.CheckConstraint(
            "item_count BETWEEN 1 AND 50",
            name="ck_attendance_scan_batch_item_count",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["coordinator_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["runtime_registration_id"],
            ["attendance_runtime_registrations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "agency_id", "group_id"],
            [
                "attendance_sessions.id",
                "attendance_sessions.agency_id",
                "attendance_sessions.group_id",
            ],
            name="fk_attendance_scan_batch_session_tenant_group",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_scan_batch_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    op.create_index(
        "ix_attendance_scan_batches_session_created",
        "attendance_scan_batches",
        ["session_id", "created_at"],
    )
    op.create_table(
        "attendance_scan_batch_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coordinator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_event_id", sa.String(length=128), nullable=False),
        sa.Column("request_ordinal", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_attendance_scan_batch_result_fingerprint",
        ),
        sa.CheckConstraint(
            "outcome IN ('counted', 'duplicate', 'rejected')",
            name="ck_attendance_scan_batch_result_outcome",
        ),
        sa.CheckConstraint(
            "(outcome IN ('counted', 'duplicate') AND passenger_id IS NOT NULL "
            "AND error_code IS NULL AND retryable = false) OR "
            "(outcome = 'rejected' AND passenger_id IS NULL AND error_code IS NOT NULL)",
            name="ck_attendance_scan_batch_result_shape",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["attendance_scan_batches.batch_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["coordinator_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "session_id",
            "client_event_id",
            name="uq_attendance_scan_batch_result_event",
        ),
    )
    op.create_index(
        "ix_attendance_scan_batch_results_batch_order",
        "attendance_scan_batch_results",
        ["batch_id", "request_ordinal"],
    )

    op.create_table(
        "attendance_discard_tombstones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coordinator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_registration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("discard_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_reference", sa.String(length=64), nullable=False),
        sa.Column("reason_category", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="accepted", nullable=False),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciliation_note", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(scan_reference) = 64",
            name="ck_attendance_discard_scan_reference",
        ),
        sa.CheckConstraint(
            "reason_category IN ('operator_discard', 'coordinator_confirmed_rescan', "
            "'wrong_group', 'expired_authorization', 'activity_closed', 'duplicate', "
            "'duplicate_local_evidence', 'passenger_not_attending', 'privacy_or_data_error', "
            "'server_rejected', 'server_terminal_rejection', 'corrupted_entry', 'other')",
            name="ck_attendance_discard_reason",
        ),
        sa.CheckConstraint(
            "status IN ('accepted', 'reconciled', 'overridden')",
            name="ck_attendance_discard_status",
        ),
        sa.CheckConstraint(
            "received_at >= discarded_at AND retention_expires_at > received_at",
            name="ck_attendance_discard_time_order",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["coordinator_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["runtime_registration_id"],
            ["attendance_runtime_registrations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "agency_id", "group_id"],
            [
                "attendance_sessions.id",
                "attendance_sessions.agency_id",
                "attendance_sessions.group_id",
            ],
            name="fk_attendance_discard_session_tenant_group",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_discard_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "coordinator_user_id",
            "discard_event_id",
            name="uq_attendance_discard_event",
        ),
    )
    op.create_index(
        "ix_attendance_discard_session_received",
        "attendance_discard_tombstones",
        ["session_id", "received_at"],
    )
    op.create_index(
        "ix_attendance_discard_retention",
        "attendance_discard_tombstones",
        ["retention_expires_at", "id"],
    )

    op.add_column(
        "identity_action_tokens",
        sa.Column(
            "token_key_id",
            sa.String(length=64),
            server_default="legacy-v1",
            nullable=False,
        ),
    )

    op.create_table(
        "identity_notification_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("recipient_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("payload_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_id", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id_hash", sa.String(length=64), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('activation', 'password_recovery', 'admin_assisted_recovery')",
            name="ck_identity_notification_purpose",
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'sms')",
            name="ck_identity_notification_channel",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'delivered', 'dead_letter')",
            name="ck_identity_notification_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= max_attempts",
            name="ck_identity_notification_attempts",
        ),
        sa.CheckConstraint(
            "length(dedupe_key) = 64",
            name="ck_identity_notification_dedupe_key",
        ),
        sa.CheckConstraint(
            "length(encryption_key_id) BETWEEN 1 AND 64",
            name="ck_identity_notification_encryption_key_id",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["action_token_id"],
            ["identity_action_tokens.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_identity_notification_outbox_dedupe"),
    )
    op.create_index(
        "ix_identity_notification_due",
        "identity_notification_outbox",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_identity_notification_expired_lease",
        "identity_notification_outbox",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "ix_identity_notification_user_created",
        "identity_notification_outbox",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_mfa_recovery_consumed_created",
        "mfa_recovery_codes",
        ["consumed_at", "created_at", "id"],
    )

    op.create_table(
        "untrusted_upload_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingestion_flow", sa.String(length=64), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("declared_media_type", sa.String(length=120), nullable=True),
        sa.Column("scanner_name", sa.String(length=64), nullable=False),
        sa.Column("scanner_version", sa.String(length=64), nullable=True),
        sa.Column("scan_status", sa.String(length=24), nullable=False),
        sa.Column("disposition", sa.String(length=16), nullable=False),
        sa.Column("detection_category", sa.String(length=80), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("quarantine_key_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("quarantine_key_version", sa.Integer(), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scan_status IN ('clean', 'infected', 'scanner_error', 'malformed', 'oversized')",
            name="ck_untrusted_upload_scan_status",
        ),
        sa.CheckConstraint(
            "disposition IN ('accepted', 'rejected', 'quarantined')",
            name="ck_untrusted_upload_disposition",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_untrusted_upload_sha256",
        ),
        sa.CheckConstraint("byte_size >= 0", name="ck_untrusted_upload_byte_size"),
        sa.CheckConstraint(
            "(disposition = 'quarantined' AND quarantine_key_ciphertext IS NOT NULL "
            "AND quarantine_key_version IS NOT NULL) OR "
            "(disposition <> 'quarantined' AND quarantine_key_ciphertext IS NULL "
            "AND quarantine_key_version IS NULL)",
            name="ck_untrusted_upload_quarantine_shape",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_untrusted_upload_scan_created",
        "untrusted_upload_scans",
        ["agency_id", "created_at", "id"],
    )
    op.create_index(
        "ix_untrusted_upload_quarantine_retention",
        "untrusted_upload_scans",
        ["disposition", "retention_expires_at", "id"],
    )

    op.create_table(
        "audit_chain_heads",
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("integrity_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_hash", sa.String(length=64), server_default="0" * 64, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("integrity_version = 1", name="ck_audit_chain_head_version"),
        sa.CheckConstraint("last_sequence >= 0", name="ck_audit_chain_head_sequence"),
        sa.CheckConstraint("length(last_hash) = 64", name="ck_audit_chain_head_hash"),
        sa.PrimaryKeyConstraint("scope_key"),
    )

    # Immutable audit snapshots retain identifiers even after their source
    # account/tenant is removed, so the old SET NULL foreign keys are removed.
    op.drop_constraint("audit_logs_agency_id_fkey", "audit_logs", type_="foreignkey")
    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.add_column(
        "audit_logs",
        sa.Column("result", sa.String(length=16), server_default="success", nullable=False),
    )
    op.add_column(
        "audit_logs",
        sa.Column("integrity_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("audit_logs", sa.Column("integrity_scope", sa.String(length=80), nullable=True))
    op.add_column("audit_logs", sa.Column("integrity_sequence", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("previous_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("entry_hash", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        "ck_audit_logs_result",
        "audit_logs",
        "result IN ('success', 'blocked', 'denied', 'failed')",
    )
    op.create_check_constraint(
        "ck_audit_logs_integrity_shape",
        "audit_logs",
        "(integrity_version = 0 AND integrity_scope IS NULL "
        "AND integrity_sequence IS NULL AND previous_hash IS NULL AND entry_hash IS NULL) "
        "OR (integrity_version = 1 AND integrity_scope IS NOT NULL "
        "AND integrity_sequence > 0 AND length(previous_hash) = 64 "
        "AND length(entry_hash) = 64)",
    )
    op.create_index(
        "uq_audit_logs_integrity_sequence",
        "audit_logs",
        ["integrity_scope", "integrity_sequence"],
        unique=True,
        postgresql_where=sa.text("integrity_version = 1"),
    )
    op.create_index(
        "ix_audit_logs_scope_created_id",
        "audit_logs",
        ["agency_id", "created_at", "id"],
    )
    op.create_index(
        "ix_audit_logs_filter_entity_result",
        "audit_logs",
        ["agency_id", "entity_type", "result", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_audit_log_mutation() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation()
        """
    )


def downgrade() -> None:
    # Downgrade removes stronger semantics but preserves pre-existing rows.
    # Re-adding the historical audit foreign keys can fail if a referenced
    # account/tenant was deleted while this revision was active; operators
    # must reconcile those identifiers before attempting such a downgrade.
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_log_mutation()")
    op.drop_index("ix_audit_logs_filter_entity_result", table_name="audit_logs")
    op.drop_index("ix_audit_logs_scope_created_id", table_name="audit_logs")
    op.drop_index("uq_audit_logs_integrity_sequence", table_name="audit_logs")
    op.drop_constraint("ck_audit_logs_integrity_shape", "audit_logs", type_="check")
    op.drop_constraint("ck_audit_logs_result", "audit_logs", type_="check")
    op.drop_column("audit_logs", "entry_hash")
    op.drop_column("audit_logs", "previous_hash")
    op.drop_column("audit_logs", "integrity_sequence")
    op.drop_column("audit_logs", "integrity_scope")
    op.drop_column("audit_logs", "integrity_version")
    op.drop_column("audit_logs", "result")
    op.create_foreign_key(
        "audit_logs_user_id_fkey",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "audit_logs_agency_id_fkey",
        "audit_logs",
        "agencies",
        ["agency_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_table("audit_chain_heads")

    op.drop_index("ix_untrusted_upload_quarantine_retention", table_name="untrusted_upload_scans")
    op.drop_index("ix_untrusted_upload_scan_created", table_name="untrusted_upload_scans")
    op.drop_table("untrusted_upload_scans")

    op.drop_index("ix_mfa_recovery_consumed_created", table_name="mfa_recovery_codes")
    op.drop_index(
        "ix_identity_notification_user_created", table_name="identity_notification_outbox"
    )
    op.drop_index(
        "ix_identity_notification_expired_lease", table_name="identity_notification_outbox"
    )
    op.drop_index("ix_identity_notification_due", table_name="identity_notification_outbox")
    op.drop_table("identity_notification_outbox")
    op.drop_column("identity_action_tokens", "token_key_id")

    op.drop_index("ix_attendance_discard_retention", table_name="attendance_discard_tombstones")
    op.drop_index(
        "ix_attendance_discard_session_received", table_name="attendance_discard_tombstones"
    )
    op.drop_table("attendance_discard_tombstones")

    op.drop_index(
        "ix_attendance_scan_batch_results_batch_order",
        table_name="attendance_scan_batch_results",
    )
    op.drop_table("attendance_scan_batch_results")
    op.drop_index(
        "ix_attendance_scan_batches_session_created",
        table_name="attendance_scan_batches",
    )
    op.drop_table("attendance_scan_batches")

    op.drop_constraint(
        "fk_attendance_record_runtime_tenant_coordinator",
        "attendance_records",
        type_="foreignkey",
    )
    op.drop_constraint("fk_attendance_record_runtime", "attendance_records", type_="foreignkey")
    op.drop_column("attendance_records", "runtime_registration_id")

    op.drop_index(
        "uq_attendance_closeout_legacy_account",
        table_name="attendance_closeout_checkpoints",
    )
    op.drop_constraint(
        "uq_attendance_closeout_checkpoint_runtime",
        "attendance_closeout_checkpoints",
        type_="unique",
    )
    op.drop_constraint(
        "fk_attendance_closeout_runtime_tenant_coordinator",
        "attendance_closeout_checkpoints",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_attendance_closeout_session_tenant",
        "attendance_closeout_checkpoints",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_attendance_closeout_runtime",
        "attendance_closeout_checkpoints",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_attendance_closeout_agency",
        "attendance_closeout_checkpoints",
        type_="foreignkey",
    )
    op.create_unique_constraint(
        "uq_attendance_closeout_checkpoint_coordinator",
        "attendance_closeout_checkpoints",
        ["session_id", "coordinator_user_id"],
    )
    op.drop_column("attendance_closeout_checkpoints", "runtime_registration_id")
    op.drop_column("attendance_closeout_checkpoints", "agency_id")

    op.drop_index(
        "ix_attendance_participants_session_coordinator",
        table_name="attendance_session_runtime_participants",
    )
    op.drop_table("attendance_session_runtime_participants")
    op.drop_index(
        "ix_attendance_runtime_native_session",
        table_name="attendance_runtime_registrations",
    )
    op.drop_index(
        "ix_attendance_runtime_coordinator_status",
        table_name="attendance_runtime_registrations",
    )
    op.drop_table("attendance_runtime_registrations")

    op.drop_index("ix_attendance_sessions_group_schedule", table_name="attendance_sessions")
    op.drop_constraint(
        "ck_attendance_sessions_schedule_version",
        "attendance_sessions",
        type_="check",
    )
    op.drop_constraint(
        "ck_attendance_sessions_schedule_timezone",
        "attendance_sessions",
        type_="check",
    )
    op.drop_constraint(
        "ck_attendance_sessions_scheduled_window",
        "attendance_sessions",
        type_="check",
    )
    op.drop_constraint(
        "uq_attendance_sessions_id_agency_group",
        "attendance_sessions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_attendance_sessions_id_agency",
        "attendance_sessions",
        type_="unique",
    )
    op.drop_column("attendance_sessions", "schedule_version")
    op.drop_column("attendance_sessions", "schedule_timezone")
    op.drop_column("attendance_sessions", "scheduled_ends_at")
    op.drop_column("attendance_sessions", "scheduled_starts_at")
    op.drop_constraint("uq_client_groups_id_agency", "client_groups", type_="unique")
    op.drop_constraint("uq_users_id_agency", "users", type_="unique")
