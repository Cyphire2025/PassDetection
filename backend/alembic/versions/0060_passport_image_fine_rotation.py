"""Allow per-degree passport image rotation.

Revision ID: 0060_fine_rotation
Revises: 0059_account_deletion
Create Date: 2026-07-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0060_fine_rotation"
down_revision = "0059_account_deletion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_passport_image_crops_rotation",
        "passport_image_crops",
        type_="check",
    )
    op.create_check_constraint(
        "ck_passport_image_crops_rotation",
        "passport_image_crops",
        "rotation_degrees >= 0 AND rotation_degrees <= 359",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_passport_image_crops_rotation",
        "passport_image_crops",
        type_="check",
    )
    op.execute(
        sa.text(
            """
            UPDATE passport_image_crops
            SET rotation_degrees = CASE
                WHEN rotation_degrees < 45 OR rotation_degrees >= 315 THEN 0
                WHEN rotation_degrees < 135 THEN 90
                WHEN rotation_degrees < 225 THEN 180
                ELSE 270
            END
            """
        )
    )
    op.create_check_constraint(
        "ck_passport_image_crops_rotation",
        "passport_image_crops",
        "rotation_degrees IN (0, 90, 180, 270)",
    )
