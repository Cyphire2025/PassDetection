"""Preserve read permissions and add explicit, default-denied effect authority."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0126_mcp_section_permissions"
down_revision = "0125_mcp_connection_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_control,mcp_grants,mcp_tokens,mcp_authorization_codes,mcp_connection_requests IN SHARE MODE")
    for table in ("mcp_control", "mcp_grants", "mcp_connection_requests"):
        op.add_column(table, sa.Column("read_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        op.add_column(table, sa.Column("write_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column(table, sa.Column("allowed_write_sections", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("mcp_control", sa.Column("allowed_write_tools", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    for table in ("mcp_grants", "mcp_connection_requests"):
        op.add_column(table, sa.Column("allowed_read_sections", postgresql.JSONB(), nullable=True))
    op.add_column("mcp_grants", sa.Column("permission_revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_check_constraint("ck_mcp_grant_permission_revision", "mcp_grants", "permission_revision >= 1")


def downgrade() -> None:
    raise RuntimeError("Retain permission decisions and use a schema-compatible recovery image; destructive downgrade is unsupported")
