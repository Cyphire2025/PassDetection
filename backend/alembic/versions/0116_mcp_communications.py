"""Preserve exact communication intentions and durable broker-publication state."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0116_mcp_communications"
down_revision = "0115_mcp_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "mcp_whatsapp_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_operations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("original_grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="SET NULL")),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broadcast_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), unique=True),
        sa.CheckConstraint("status IN ('prepared','queued','cancelled','blocked','completed')", name="ck_mcp_whatsapp_plan_status"),
        sa.CheckConstraint("revision >= 1", name="ck_mcp_whatsapp_plan_revision"),
        sa.CheckConstraint("expires_at > prepared_at", name="ck_mcp_whatsapp_plan_expiry"),
    )
    op.create_index("ix_mcp_whatsapp_plans_user_prepared", "mcp_whatsapp_plans", ["user_id", "prepared_at"])
    op.create_table(
        "mcp_whatsapp_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_whatsapp_plans.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("publication_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','published','completed','cancelled','blocked')", name="ck_mcp_whatsapp_outbox_status"),
        sa.CheckConstraint("publication_attempts >= 0", name="ck_mcp_whatsapp_outbox_attempts"),
    )
    op.create_index("ix_mcp_whatsapp_outbox_due", "mcp_whatsapp_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_whatsapp_plans, mcp_whatsapp_outbox IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM mcp_whatsapp_plans)")).scalar_one():
        raise RuntimeError("MCP communication history must be retained; roll back application code with the additive schema in place.")
    op.drop_table("mcp_whatsapp_outbox")
    op.drop_table("mcp_whatsapp_plans")
