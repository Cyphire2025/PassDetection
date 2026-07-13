"""Add persistent saved state and display order to rooming rooms.

Revision ID: 0017_rooming_room_state
Revises: 0016_rooming_lists
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_rooming_room_state"
down_revision = "0016_rooming_lists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rooming_rooms", sa.Column("is_saved", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("rooming_rooms", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE rooming_rooms SET sort_order = ordered.position - 1 FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY hotel_id ORDER BY created_at, room_number) AS position FROM rooming_rooms) AS ordered WHERE rooming_rooms.id = ordered.id")
    op.alter_column("rooming_rooms", "is_saved", server_default=None)
    op.alter_column("rooming_rooms", "sort_order", server_default=None)


def downgrade() -> None:
    op.drop_column("rooming_rooms", "sort_order")
    op.drop_column("rooming_rooms", "is_saved")
