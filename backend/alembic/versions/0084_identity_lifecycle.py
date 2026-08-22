"""Add workforce credential lifecycle, MFA, and session fencing.

Revision ID: 0084_identity_lifecycle
Revises: 0083_attendance_closeout
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0084_identity_lifecycle"
down_revision = "0083_attendance_closeout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_security_states",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_state", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("session_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("mfa_secret_ciphertext", sa.String(length=512), nullable=True),
        sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_last_counter", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "credential_state IN ('invited', 'active')",
            name="ck_user_security_credential_state",
        ),
        sa.CheckConstraint("session_version >= 1", name="ck_user_security_session_version"),
        sa.CheckConstraint(
            "(mfa_secret_ciphertext IS NULL AND mfa_enabled_at IS NULL "
            "AND mfa_last_counter IS NULL) OR "
            "(mfa_secret_ciphertext IS NOT NULL AND mfa_enabled_at IS NOT NULL)",
            name="ck_user_security_mfa_shape",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_user_security_mfa_required",
        "user_security_states",
        ["mfa_required", "mfa_enabled_at"],
    )

    # Existing dashboard principals remain usable, but PII-capable and
    # administrative roles must enroll MFA at their next password login.
    op.execute(
        sa.text(
            """
            INSERT INTO user_security_states (
                user_id, credential_state, session_version, password_changed_at,
                mfa_required, created_at, updated_at
            )
            SELECT id, 'active', 1, updated_at,
                   role IN ('super_admin', 'agency_admin', 'agency_manager', 'agency_staff'),
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
              FROM users
            """
        )
    )

    op.create_table(
        "identity_action_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('activation', 'password_recovery')",
            name="ck_identity_action_token_purpose",
        ),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_identity_action_token_hash"),
        sa.CheckConstraint("expires_at > created_at", name="ck_identity_action_token_expiry"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_identity_action_user_purpose",
        "identity_action_tokens",
        ["user_id", "purpose", "created_at"],
    )
    op.create_index(
        "ix_identity_action_expiry",
        "identity_action_tokens",
        ["expires_at", "consumed_at", "invalidated_at"],
    )
    op.create_index(
        "uq_identity_action_active_user_purpose",
        "identity_action_tokens",
        ["user_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL AND invalidated_at IS NULL"),
    )

    op.create_table(
        "dashboard_auth_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("challenge_token_hash", sa.String(length=64), nullable=False),
        sa.Column("pending_secret_ciphertext", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('mfa_login', 'mfa_enrollment')",
            name="ck_dashboard_auth_challenge_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed', 'expired', 'locked', 'cancelled')",
            name="ck_dashboard_auth_challenge_status",
        ),
        sa.CheckConstraint("length(challenge_token_hash) = 64", name="ck_dashboard_auth_token_hash"),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= max_attempts",
            name="ck_dashboard_auth_attempts",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_dashboard_auth_expiry"),
        sa.CheckConstraint(
            "(purpose = 'mfa_enrollment' AND pending_secret_ciphertext IS NOT NULL) OR "
            "(purpose = 'mfa_login' AND pending_secret_ciphertext IS NULL)",
            name="ck_dashboard_auth_pending_secret",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_token_hash"),
    )
    op.create_index(
        "ix_dashboard_auth_user_created",
        "dashboard_auth_challenges",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_dashboard_auth_expiry_status",
        "dashboard_auth_challenges",
        ["expires_at", "status"],
    )
    op.create_index(
        "uq_dashboard_auth_pending_user",
        "dashboard_auth_challenges",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(code_hash) = 64", name="ck_mfa_recovery_code_hash"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        "ix_mfa_recovery_user_available",
        "mfa_recovery_codes",
        ["user_id", "consumed_at"],
    )

    op.add_column(
        "refresh_tokens",
        sa.Column("session_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("authentication_methods", sa.String(length=64), server_default="pwd", nullable=False),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("mfa_authenticated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_refresh_token_session_version",
        "refresh_tokens",
        "session_version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_refresh_token_session_version", "refresh_tokens", type_="check")
    op.drop_column("refresh_tokens", "mfa_authenticated_at")
    op.drop_column("refresh_tokens", "authentication_methods")
    op.drop_column("refresh_tokens", "session_version")
    op.drop_index("ix_mfa_recovery_user_available", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_index("uq_dashboard_auth_pending_user", table_name="dashboard_auth_challenges")
    op.drop_index("ix_dashboard_auth_expiry_status", table_name="dashboard_auth_challenges")
    op.drop_index("ix_dashboard_auth_user_created", table_name="dashboard_auth_challenges")
    op.drop_table("dashboard_auth_challenges")
    op.drop_index(
        "uq_identity_action_active_user_purpose",
        table_name="identity_action_tokens",
    )
    op.drop_index("ix_identity_action_expiry", table_name="identity_action_tokens")
    op.drop_index("ix_identity_action_user_purpose", table_name="identity_action_tokens")
    op.drop_table("identity_action_tokens")
    op.drop_index("ix_user_security_mfa_required", table_name="user_security_states")
    op.drop_table("user_security_states")
