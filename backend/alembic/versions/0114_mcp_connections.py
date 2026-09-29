"""Add independently revocable MCP authority, disabled until qualified activation."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0114_mcp_connections"
down_revision = "0113_document_follow_up"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "mcp_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_mcp_control_singleton"),
    )
    op.execute("INSERT INTO mcp_control (id, enabled, updated_at) VALUES (1, false, CURRENT_TIMESTAMP)")
    op.create_table(
        "mcp_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("resource", sa.String(512), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("security_version", sa.Integer(), nullable=False),
        sa.Column("mfa_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.String(64)),
        sa.CheckConstraint("security_version >= 1", name="ck_mcp_grant_security_version"),
        sa.CheckConstraint("expires_at > created_at", name="ck_mcp_grant_expiry"),
    )
    op.create_index("ix_mcp_grants_user_created", "mcp_grants", ["user_id", "created_at"])
    op.create_table(
        "mcp_authorization_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("redirect_uri", sa.String(1024), nullable=False),
        sa.Column("code_challenge", sa.String(43), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "mcp_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('access', 'refresh')", name="ck_mcp_token_kind"),
    )
    op.create_index("ix_mcp_tokens_grant_kind", "mcp_tokens", ["grant_id", "kind"])
    op.create_table(
        "mcp_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("initial_grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation_name", sa.String(120), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("idempotency_hash", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("initial_result", postgresql.JSONB(), nullable=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("stage", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_entities", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "operation_name", "idempotency_hash", name="uq_mcp_operation_user_name_key"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'unknown')", name="ck_mcp_operation_status"),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="ck_mcp_operation_progress"),
        sa.CheckConstraint("revision >= 0", name="ck_mcp_operation_revision"),
        sa.CheckConstraint("status != 'succeeded' OR progress = 1", name="ck_mcp_operation_success_progress"),
    )
    op.create_index("ix_mcp_operations_user_created", "mcp_operations", ["user_id", "created_at"])
    op.create_index("ix_mcp_operations_workflow", "mcp_operations", ["workflow_id"])
    op.create_table(
        "mcp_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("handle_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False, unique=True),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("download_completed_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("export_history_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("passport_export_history.id", ondelete="CASCADE"), unique=True),
        sa.Column("export_checkpoint_sha256", sa.String(64)),
        sa.CheckConstraint("direction IN ('upload', 'export')", name="ck_mcp_artifact_direction"),
        sa.CheckConstraint("byte_size > 0", name="ck_mcp_artifact_size"),
        sa.CheckConstraint("expires_at > created_at", name="ck_mcp_artifact_expiry"),
        sa.CheckConstraint("delivered_at IS NULL OR (direction = 'export' AND download_completed_at IS NOT NULL)", name="ck_mcp_artifact_delivery"),
        sa.CheckConstraint("export_history_id IS NULL OR direction = 'export'", name="ck_mcp_artifact_history"),
        sa.CheckConstraint("(export_history_id IS NULL) = (export_checkpoint_sha256 IS NULL)", name="ck_mcp_artifact_checkpoint"),
    )
    op.create_index("ix_mcp_artifacts_expiry", "mcp_artifacts", ["expires_at"])
    op.create_index("ix_mcp_artifacts_grant_created", "mcp_artifacts", ["grant_id", "created_at"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_control, mcp_grants, mcp_authorization_codes, mcp_tokens, mcp_operations, mcp_artifacts IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM mcp_grants)")).scalar_one():
        raise RuntimeError("MCP connection history must be retained; roll back application code with the additive schema in place.")
    op.drop_table("mcp_artifacts")
    op.drop_table("mcp_operations")
    op.drop_table("mcp_tokens")
    op.drop_table("mcp_authorization_codes")
    op.drop_table("mcp_grants")
    op.drop_table("mcp_control")
