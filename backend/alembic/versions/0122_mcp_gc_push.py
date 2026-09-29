"""Retain exact GC push plans and per-notification MCP dispatch origins."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0122_mcp_gc_push"
down_revision = "0121_whatsapp_send_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    alphabet = sa.column("snapshot_hash")
    for character in "0123456789abcdef":
        alphabet = sa.func.replace(alphabet, character, "")
    op.create_table(
        "mcp_gc_push_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_operations.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("original_grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="SET NULL")),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gc_notification_drafts.id", ondelete="SET NULL")),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), unique=True),
        sa.CheckConstraint("status IN ('prepared','queued','blocked','completed')", name="ck_mcp_gc_push_plan_status"),
        sa.CheckConstraint("revision >= 1", name="ck_mcp_gc_push_plan_revision"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_mcp_gc_push_plan_hash_length"),
        sa.CheckConstraint(alphabet == "", name="ck_mcp_gc_push_plan_hash_alphabet"),
        sa.CheckConstraint("expires_at > prepared_at", name="ck_mcp_gc_push_plan_expiry"),
    )
    op.create_index("ix_mcp_gc_push_plans_user_prepared", "mcp_gc_push_plans", ["user_id", "prepared_at"])
    op.create_table(
        "mcp_gc_push_origins",
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mobile_notifications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gc_notification_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_gc_push_plans.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mcp_gc_push_origins_plan", "mcp_gc_push_origins", ["plan_id", "notification_id"])
    op.create_index("ix_mcp_gc_push_origins_batch", "mcp_gc_push_origins", ["batch_id"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_gc_push_plans, mcp_gc_push_origins IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM mcp_gc_push_plans) OR EXISTS (SELECT 1 FROM mcp_gc_push_origins)")).scalar_one():
        raise RuntimeError("MCP GC push history and origins must be retained; keep the additive schema during recovery.")
    op.drop_table("mcp_gc_push_origins")
    op.drop_table("mcp_gc_push_plans")
