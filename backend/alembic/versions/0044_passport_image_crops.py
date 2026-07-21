"""Add non-destructive passport image crop metadata.

Revision ID: 0044_passport_image_crops
Revises: 0043_rejected_imported_fields
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0044_passport_image_crops"
down_revision = "0043_rejected_imported_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passport_image_crops",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_type", sa.String(length=24), nullable=False),
        sa.Column("source_storage_key", sa.String(length=512), nullable=False),
        sa.Column("derived_storage_key", sa.String(length=512), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("crop_x", sa.Float(), nullable=False),
        sa.Column("crop_y", sa.Float(), nullable=False),
        sa.Column("crop_width", sa.Float(), nullable=False),
        sa.Column("crop_height", sa.Float(), nullable=False),
        sa.Column("rotation_degrees", sa.Integer(), nullable=False),
        sa.Column("source_width", sa.Integer(), nullable=False),
        sa.Column("source_height", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "image_type IN ('visa_photo', 'passport_front', 'passport_back')",
            name="ck_passport_image_crops_type",
        ),
        sa.CheckConstraint(
            "rotation_degrees IN (0, 90, 180, 270)",
            name="ck_passport_image_crops_rotation",
        ),
        sa.CheckConstraint(
            "crop_x >= 0 AND crop_y >= 0 AND crop_width >= 0.08 AND crop_height >= 0.08 "
            "AND crop_x + crop_width <= 1.000001 "
            "AND crop_y + crop_height <= 1.000001",
            name="ck_passport_image_crops_bounds",
        ),
        sa.CheckConstraint(
            "source_width > 0 AND source_height > 0",
            name="ck_passport_image_crops_source_size",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_passport_image_crops_revision",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["passport_submissions.id"],
            name="fk_passport_image_crops_submission",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_passport_image_crops_updated_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_passport_image_crops"),
        sa.UniqueConstraint(
            "submission_id",
            "image_type",
            name="uq_passport_image_crops_submission_type",
        ),
    )
    op.create_index(
        "ix_passport_image_crops_submission_id",
        "passport_image_crops",
        ["submission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_passport_image_crops_submission_id",
        table_name="passport_image_crops",
    )
    op.drop_table("passport_image_crops")
