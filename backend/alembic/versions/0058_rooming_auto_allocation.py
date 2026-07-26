"""Add hotel passenger selection and deterministic auto-allocation state.

Revision ID: 0058_rooming_auto
Revises: 0057_meal_categories
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0058_rooming_auto"
down_revision = "0057_meal_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rooming_hotels",
        sa.Column(
            "allocation_priority_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "rooming_hotels",
        sa.Column(
            "allocation_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "rooming_hotels",
        sa.Column("allocation_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "rooming_hotels",
        sa.Column(
            "allocation_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_table(
        "rooming_hotel_passengers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hotel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_vip",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            name="fk_rooming_hotel_passengers_agency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["client_groups.id"],
            name="fk_rooming_hotel_passengers_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["rooming_hotels.id"],
            name="fk_rooming_hotel_passengers_hotel",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["passenger_id"],
            ["passport_submissions.id"],
            name="fk_rooming_hotel_passengers_passenger",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rooming_hotel_passengers"),
        sa.UniqueConstraint(
            "group_id",
            "passenger_id",
            name="uq_rooming_hotel_passengers_group_passenger",
        ),
        sa.UniqueConstraint(
            "hotel_id",
            "passenger_id",
            name="uq_rooming_hotel_passengers_hotel_passenger",
        ),
    )
    op.create_index(
        "ix_rooming_hotel_passengers_agency_id",
        "rooming_hotel_passengers",
        ["agency_id"],
    )
    op.create_index(
        "ix_rooming_hotel_passengers_group_id",
        "rooming_hotel_passengers",
        ["group_id"],
    )
    op.create_index(
        "ix_rooming_hotel_passengers_hotel_id",
        "rooming_hotel_passengers",
        ["hotel_id"],
    )
    op.create_index(
        "ix_rooming_hotel_passengers_passenger_id",
        "rooming_hotel_passengers",
        ["passenger_id"],
    )
    op.create_index(
        "ix_rooming_hotel_passengers_group_hotel",
        "rooming_hotel_passengers",
        ["group_id", "hotel_id"],
    )

    # Preserve the effective invariant maintained by the legacy route: one
    # assignment per passenger across a group's hotels. If historical data
    # violated it, the newest assignment is the authoritative membership.
    op.execute(
        sa.text(
            """
            INSERT INTO rooming_hotel_passengers (
                id,
                agency_id,
                group_id,
                hotel_id,
                passenger_id,
                is_vip,
                created_at,
                updated_at
            )
            SELECT
                md5(ranked.group_id::text || ':' || ranked.passenger_id::text)::uuid,
                ranked.agency_id,
                ranked.group_id,
                ranked.hotel_id,
                ranked.passenger_id,
                ranked.is_vip,
                ranked.assigned_at,
                CURRENT_TIMESTAMP
            FROM (
                SELECT
                    hotel.agency_id,
                    hotel.group_id,
                    assignment.hotel_id,
                    assignment.passenger_id,
                    assignment.assigned_at,
                    (
                        room.allocation_tag = 'vip'
                        OR COALESCE(
                            preference.special_requests @> '["vip"]'::jsonb,
                            false
                        )
                    ) AS is_vip,
                    ROW_NUMBER() OVER (
                        PARTITION BY hotel.group_id, assignment.passenger_id
                        ORDER BY assignment.assigned_at DESC, assignment.id DESC
                    ) AS row_number
                FROM rooming_assignments AS assignment
                JOIN rooming_hotels AS hotel ON hotel.id = assignment.hotel_id
                JOIN rooming_rooms AS room ON room.id = assignment.room_id
                LEFT JOIN rooming_passenger_preferences AS preference
                    ON preference.hotel_id = assignment.hotel_id
                    AND preference.passenger_id = assignment.passenger_id
            ) AS ranked
            WHERE ranked.row_number = 1
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE rooming_hotels AS hotel
            SET
                allocation_fingerprint = repeat('0', 64),
                allocation_revision = 1,
                allocation_updated_at = CURRENT_TIMESTAMP
            WHERE EXISTS (
                SELECT 1
                FROM rooming_checkins AS checkin
                WHERE checkin.hotel_id = hotel.id
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_table("rooming_hotel_passengers")
    op.drop_column("rooming_hotels", "allocation_updated_at")
    op.drop_column("rooming_hotels", "allocation_fingerprint")
    op.drop_column("rooming_hotels", "allocation_revision")
    op.drop_column("rooming_hotels", "allocation_priority_fields")
