"""Persist Visa AI generations and version stronger image sharpening.

Revision ID: 0048_visa_ai_image_library
Revises: 0047_passport_image_edits
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0048_visa_ai_image_library"
down_revision = "0047_passport_image_edits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "passport_image_crops",
        sa.Column(
            "sharpness_algorithm_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_passport_image_crops_sharpness_algorithm_version",
        "passport_image_crops",
        "sharpness_algorithm_version IN (1, 2)",
    )
    op.create_table(
        "passport_visa_ai_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_source_storage_key", sa.String(length=512), nullable=False),
        sa.Column("input_storage_key", sa.String(length=512), nullable=False),
        sa.Column("generated_storage_key", sa.String(length=512), nullable=False),
        sa.Column("prompt", sa.String(length=1000), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_passport_visa_ai_images_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["passport_submissions.id"],
            name="fk_passport_visa_ai_images_submission",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_passport_visa_ai_images"),
        sa.UniqueConstraint(
            "submission_id",
            "generated_storage_key",
            name="uq_passport_visa_ai_images_submission_storage_key",
        ),
    )
    op.create_index(
        "ix_passport_visa_ai_images_submission_id",
        "passport_visa_ai_images",
        ["submission_id"],
        unique=False,
    )
    op.create_index(
        "ix_passport_visa_ai_images_created_by_user_id",
        "passport_visa_ai_images",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_passport_visa_ai_images_submission_created",
        "passport_visa_ai_images",
        ["submission_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_passport_visa_ai_images_submission_created",
        table_name="passport_visa_ai_images",
    )
    op.drop_index(
        "ix_passport_visa_ai_images_created_by_user_id",
        table_name="passport_visa_ai_images",
    )
    op.drop_index(
        "ix_passport_visa_ai_images_submission_id",
        table_name="passport_visa_ai_images",
    )
    op.drop_table("passport_visa_ai_images")
    op.drop_constraint(
        "ck_passport_image_crops_sharpness_algorithm_version",
        "passport_image_crops",
        type_="check",
    )
    op.drop_column("passport_image_crops", "sharpness_algorithm_version")
