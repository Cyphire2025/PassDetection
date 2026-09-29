"""Bind a staged PDF to one durable append-only ingestion intention."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0118_mcp_pdf_ingestion"
down_revision = "0117_mcp_dispatch_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("mcp_artifacts", sa.Column("ingestion_operation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint("mcp_artifacts_ingestion_operation_id_key", "mcp_artifacts", ["ingestion_operation_id"])
    op.create_foreign_key("mcp_artifacts_ingestion_operation_id_fkey", "mcp_artifacts", "mcp_operations",
                          ["ingestion_operation_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_artifacts IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM mcp_artifacts WHERE ingestion_operation_id IS NOT NULL)")).scalar_one():
        raise RuntimeError("MCP ingestion history must be retained; roll back application code with the additive schema in place.")
    op.drop_constraint("mcp_artifacts_ingestion_operation_id_fkey", "mcp_artifacts", type_="foreignkey")
    op.drop_constraint("mcp_artifacts_ingestion_operation_id_key", "mcp_artifacts", type_="unique")
    op.drop_column("mcp_artifacts", "ingestion_operation_id")
