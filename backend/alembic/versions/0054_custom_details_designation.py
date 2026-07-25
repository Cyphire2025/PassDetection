"""Add typed group details and repeatable free-text upload fields.

Revision ID: 0054_custom_details
Revises: 0053_shared_attendance
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0054_custom_details"
down_revision = "0053_shared_attendance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column(
            "designation_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "client_groups",
        sa.Column(
            "agency_dealership_name_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "client_groups",
        sa.Column(
            "custom_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column(
            "custom_detail_answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("passport_submissions", "custom_detail_answers")
    op.drop_column("client_groups", "custom_details")
    op.drop_column("client_groups", "agency_dealership_name_enabled")
    op.drop_column("client_groups", "designation_enabled")
