"""Add independent connection access switches and optional device labels.

Existing grants keep their current authority and remain enabled. Disabling a
connection pauses its credentials without revoking or expanding its capabilities.
"""

import sqlalchemy as sa

from alembic import op

revision = "0124_mcp_device_access"
down_revision = "0123_mcp_read_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "mcp_grants",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("mcp_grants", sa.Column("device_platform", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_mcp_grant_device_platform",
        "mcp_grants",
        "device_platform IS NULL OR device_platform IN ('Windows', 'macOS', 'Other')",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Retain connection access decisions and use a schema-compatible recovery image; "
        "destructive downgrade is unsupported"
    )
