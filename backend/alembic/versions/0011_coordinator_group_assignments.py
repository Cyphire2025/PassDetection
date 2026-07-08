"""Add coordinator group assignments.

Revision ID: 0011_coord_group_assign
Revises: 0010_tour_operations_foundation
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_coord_group_assign"
down_revision = "0010_tour_operations_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coordinator_group_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coordinator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["coordinator_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_coordinator_group_assignments_active", "coordinator_group_assignments", ["active"])
    op.create_index("ix_coordinator_group_assignments_agency_id", "coordinator_group_assignments", ["agency_id"])
    op.create_index("ix_coordinator_group_assignments_group_id", "coordinator_group_assignments", ["group_id"])
    op.create_index("ix_coordinator_group_assignments_coordinator_user_id", "coordinator_group_assignments", ["coordinator_user_id"])
    op.create_index(
        "ix_coordinator_group_assignments_group_active",
        "coordinator_group_assignments",
        ["group_id", "active"],
    )
    op.create_index(
        "ix_coordinator_group_assignments_coordinator_active",
        "coordinator_group_assignments",
        ["coordinator_user_id", "active"],
    )
    op.create_index(
        "uq_coordinator_group_assignments_active_pair",
        "coordinator_group_assignments",
        ["group_id", "coordinator_user_id"],
        unique=True,
        postgresql_where=sa.text("active = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_coordinator_group_assignments_active_pair", table_name="coordinator_group_assignments")
    op.drop_index("ix_coordinator_group_assignments_coordinator_active", table_name="coordinator_group_assignments")
    op.drop_index("ix_coordinator_group_assignments_group_active", table_name="coordinator_group_assignments")
    op.drop_index("ix_coordinator_group_assignments_coordinator_user_id", table_name="coordinator_group_assignments")
    op.drop_index("ix_coordinator_group_assignments_group_id", table_name="coordinator_group_assignments")
    op.drop_index("ix_coordinator_group_assignments_agency_id", table_name="coordinator_group_assignments")
    op.drop_index("ix_coordinator_group_assignments_active", table_name="coordinator_group_assignments")
    op.drop_table("coordinator_group_assignments")
