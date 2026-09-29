"""Keep an MCP dispatch marker even if an existing manual flow removes its plan."""

import sqlalchemy as sa

from alembic import op

revision = "0117_mcp_dispatch_origin"
down_revision = "0116_mcp_communications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("mcp_whatsapp_outbox_plan_id_fkey", "mcp_whatsapp_outbox", type_="foreignkey")
    op.alter_column("mcp_whatsapp_outbox", "plan_id", nullable=True)
    op.create_foreign_key("mcp_whatsapp_outbox_plan_id_fkey", "mcp_whatsapp_outbox", "mcp_whatsapp_plans",
                          ["plan_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_whatsapp_outbox IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM mcp_whatsapp_outbox)")).scalar_one():
        raise RuntimeError("MCP dispatch origins must be retained; roll back application code with the additive schema in place.")
    op.drop_constraint("mcp_whatsapp_outbox_plan_id_fkey", "mcp_whatsapp_outbox", type_="foreignkey")
    op.alter_column("mcp_whatsapp_outbox", "plan_id", nullable=False)
    op.create_foreign_key("mcp_whatsapp_outbox_plan_id_fkey", "mcp_whatsapp_outbox", "mcp_whatsapp_plans",
                          ["plan_id"], ["id"], ondelete="CASCADE")
