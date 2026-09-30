"""Add sidebar read authority without changing any grants or business records.

New/disabled control rows deny all business sections. The existing enabled
singleton retains the explicitly reviewed observational sections only when an
unrevoked, unexpired read grant already exists. No grant/capability is widened.
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0123_mcp_read_sections"
down_revision = "0122_mcp_gc_push"
branch_labels = None
depends_on = None

_PRESERVED_SECTIONS = [
    "all_groups", "analytics", "coordinators", "dashboard", "documents",
    "gc_app", "group_links", "manager", "menu", "old_data", "operations_inbox",
    "rooming_lists", "staff", "tour_ops", "whatsapp",
]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("mcp_control", sa.Column("allowed_read_sections", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("mcp_control", sa.Column("read_access_revision", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.create_check_constraint("ck_mcp_control_read_access_revision", "mcp_control", "read_access_revision >= 1")
    # Fixed migration data, independent of future application registry edits.
    op.execute(sa.text("""
        UPDATE mcp_control SET allowed_read_sections = CAST(:sections AS jsonb)
        WHERE id = 1 AND enabled = true AND EXISTS (
            SELECT 1 FROM mcp_grants
            WHERE revoked_at IS NULL AND expires_at > CURRENT_TIMESTAMP
              AND capabilities @> '["mcp:read"]'::jsonb
        )
    """).bindparams(sections=json.dumps(_PRESERVED_SECTIONS)))


def downgrade() -> None:
    raise RuntimeError("Retain section authority and use a schema-compatible recovery image; destructive downgrade is unsupported")
