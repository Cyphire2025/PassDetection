"""Extend non-destructive image crops with sharpness and Visa AI sources.

Revision ID: 0047_passport_image_edits
Revises: 0046_agent_employee_code
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0047_passport_image_edits"
down_revision = "0046_agent_employee_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "passport_image_crops",
        sa.Column("edit_source_storage_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "passport_image_crops",
        sa.Column(
            "sharpness",
            sa.Float(),
            server_default=sa.text("1.0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_passport_image_crops_sharpness",
        "passport_image_crops",
        "sharpness >= 1.0 AND sharpness <= 3.0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_passport_image_crops_sharpness",
        "passport_image_crops",
        type_="check",
    )
    op.drop_column("passport_image_crops", "sharpness")
    op.drop_column("passport_image_crops", "edit_source_storage_key")
