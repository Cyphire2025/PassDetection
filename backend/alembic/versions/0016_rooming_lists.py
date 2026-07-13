"""Add hotel rooming list allocation tables.

Revision ID: 0016_rooming_lists
Revises: 0015_internal_accounts
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_rooming_lists"
down_revision = "0015_internal_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rooming_hotels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hotel_name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("check_in_date", sa.Date(), nullable=True),
        sa.Column("check_out_date", sa.Date(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("hotel_name <> ''", name="ck_rooming_hotels_name"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rooming_hotels_agency_id", "rooming_hotels", ["agency_id"])
    op.create_index("ix_rooming_hotels_group_id", "rooming_hotels", ["group_id"])
    op.create_index("ix_rooming_hotels_group_created", "rooming_hotels", ["group_id", "created_at"])

    op.create_table(
        "rooming_rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hotel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_number", sa.String(length=32), nullable=False),
        sa.Column("room_type", sa.String(length=16), nullable=False, server_default="twin"),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("allocation_tag", sa.String(length=16), nullable=False, server_default="mixed"),
        sa.Column("roommate_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("room_type IN ('single', 'twin', 'triple')", name="ck_rooming_rooms_type"),
        sa.CheckConstraint("capacity IN (1, 2, 3)", name="ck_rooming_rooms_capacity"),
        sa.CheckConstraint("allocation_tag IN ('mixed', 'male', 'female', 'family', 'couple')", name="ck_rooming_rooms_tag"),
        sa.ForeignKeyConstraint(["hotel_id"], ["rooming_hotels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hotel_id", "room_number", name="uq_rooming_rooms_hotel_number"),
    )
    op.create_index("ix_rooming_rooms_hotel_id", "rooming_rooms", ["hotel_id"])
    op.create_index("ix_rooming_rooms_hotel_number", "rooming_rooms", ["hotel_id", "room_number"])

    op.create_table(
        "rooming_passenger_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hotel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocation_tag", sa.String(length=16), nullable=False, server_default="unspecified"),
        sa.Column("special_requests", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("roommate_notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("allocation_tag IN ('unspecified', 'male', 'female', 'family', 'couple')", name="ck_rooming_preferences_tag"),
        sa.ForeignKeyConstraint(["hotel_id"], ["rooming_hotels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passenger_id"], ["passport_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_preferences_hotel_passenger"),
    )
    op.create_index("ix_rooming_preferences_hotel_id", "rooming_passenger_preferences", ["hotel_id"])
    op.create_index("ix_rooming_preferences_passenger_id", "rooming_passenger_preferences", ["passenger_id"])
    op.create_index("ix_rooming_preferences_hotel_passenger", "rooming_passenger_preferences", ["hotel_id", "passenger_id"])

    op.create_table(
        "rooming_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hotel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["rooming_hotels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["rooming_rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passenger_id"], ["passport_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_assignments_hotel_passenger"),
        sa.UniqueConstraint("room_id", "passenger_id", name="uq_rooming_assignments_room_passenger"),
    )
    op.create_index("ix_rooming_assignments_hotel_id", "rooming_assignments", ["hotel_id"])
    op.create_index("ix_rooming_assignments_room_id", "rooming_assignments", ["room_id"])
    op.create_index("ix_rooming_assignments_passenger_id", "rooming_assignments", ["passenger_id"])
    op.create_index("ix_rooming_assignments_room_position", "rooming_assignments", ["room_id", "position"])


def downgrade() -> None:
    op.drop_table("rooming_assignments")
    op.drop_table("rooming_passenger_preferences")
    op.drop_table("rooming_rooms")
    op.drop_table("rooming_hotels")
