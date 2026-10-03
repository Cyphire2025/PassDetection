"""Retain reviewed document delivery plans and durable publication markers."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0128_mcp_document_delivery"
down_revision = "0127_mcp_native_transfers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_control,mcp_grants,mcp_tokens,mcp_authorization_codes,mcp_connection_requests IN SHARE MODE")
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "mcp_document_delivery_plans",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("operation_id", uuid, sa.ForeignKey("mcp_operations.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_grant_id", uuid, sa.ForeignKey("mcp_grants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agency_id", uuid, sa.ForeignKey("agencies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("group_id", uuid, sa.ForeignKey("client_groups.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_batch_id", uuid, sa.ForeignKey("document_distribution_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("send_batch_id", uuid, unique=True),
        sa.CheckConstraint("status IN ('prepared','queued','blocked','completed')", name="ck_mcp_document_plan_status"),
        sa.CheckConstraint("expires_at > prepared_at", name="ck_mcp_document_plan_expiry"),
    )
    op.create_index("ix_mcp_document_plans_user_prepared", "mcp_document_delivery_plans", ["user_id", "prepared_at"])
    op.create_table(
        "mcp_document_delivery_outbox",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("plan_id", uuid, sa.ForeignKey("mcp_document_delivery_plans.id", ondelete="SET NULL"), unique=True),
        sa.Column("send_batch_id", uuid, nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("publication_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','published','blocked','completed')", name="ck_mcp_document_outbox_status"),
        sa.CheckConstraint("publication_attempts >= 0", name="ck_mcp_document_outbox_attempts"),
    )
    op.create_index("ix_mcp_document_outbox_due", "mcp_document_delivery_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    raise RuntimeError("Document delivery authority and attempt history must be retained")
