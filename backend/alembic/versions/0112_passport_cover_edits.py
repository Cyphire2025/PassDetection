"""Allow non-destructive edits and image-library history for passport covers."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0112_passport_cover_edits"
down_revision = "0111_roster_revision"
branch_labels = None
depends_on = None

_TABLES = (
    ("passport_image_crops", "ck_passport_image_crops_type"),
    ("passport_image_library_items", "ck_passport_image_library_items_type"),
)
_ORIGINAL_TYPES = "'visa_photo', 'passport_front', 'passport_back'"
_COVER_TYPES = "'passport_cover', 'passport_back_cover'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, constraint in _TABLES:
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(
            constraint, table, f"image_type IN ({_ORIGINAL_TYPES}, {_COVER_TYPES})"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Prevent a concurrent cover edit between the preflight and the constraint change.
    op.execute(
        "LOCK TABLE passport_image_crops, passport_image_library_items "
        "IN ACCESS EXCLUSIVE MODE"
    )
    connection = op.get_bind()
    for table, _ in _TABLES:
        has_covers = connection.execute(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE image_type IN ({_COVER_TYPES}))")
        ).scalar_one()
        if has_covers:
            raise RuntimeError(
                "Cannot downgrade passport cover editing while cover edits or library "
                "history exist. Keep this migration to preserve those images."
            )
    for table, constraint in _TABLES:
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, f"image_type IN ({_ORIGINAL_TYPES})")
