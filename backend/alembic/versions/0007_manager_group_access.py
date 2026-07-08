"""Add manager group access assignments.

Revision ID: 0007_manager_group_access
Revises: 0006_enterprise_processing
Create Date: 2026-07-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_manager_group_access"
down_revision = "0006_enterprise_processing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_group_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manager_id", "group_id", name="uq_manager_group_access_manager_group"),
    )
    op.create_index("ix_manager_group_access_agency_id", "manager_group_access", ["agency_id"])
    op.create_index("ix_manager_group_access_group_id", "manager_group_access", ["group_id"])
    op.create_index("ix_manager_group_access_manager_id", "manager_group_access", ["manager_id"])
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.drop_index("ix_manager_group_access_manager_id", table_name="manager_group_access")
    op.drop_index("ix_manager_group_access_group_id", table_name="manager_group_access")
    op.drop_index("ix_manager_group_access_agency_id", table_name="manager_group_access")
    op.drop_table("manager_group_access")
