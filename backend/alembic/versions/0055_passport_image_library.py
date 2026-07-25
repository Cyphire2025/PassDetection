"""Add one shared library for original, manual, and AI passport images.

Revision ID: 0055_image_library
Revises: 0054_custom_details
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0055_image_library"
down_revision = "0054_custom_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passport_image_library_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("original_source_storage_key", sa.String(length=512), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("prompt", sa.String(length=1000), nullable=True),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "image_type IN ('visa_photo', 'passport_front', 'passport_back')",
            name="ck_passport_image_library_items_type",
        ),
        sa.CheckConstraint(
            "source IN ('original', 'manual', 'ai_generated')",
            name="ck_passport_image_library_items_source",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_passport_image_library_items_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["passport_submissions.id"],
            name="fk_passport_image_library_items_submission",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_passport_image_library_items"),
        sa.UniqueConstraint(
            "submission_id",
            "image_type",
            "storage_key",
            name="uq_passport_image_library_items_storage",
        ),
    )
    op.create_index(
        "ix_passport_image_library_items_submission_id",
        "passport_image_library_items",
        ["submission_id"],
        unique=False,
    )
    op.create_index(
        "ix_passport_image_library_items_created_by_user_id",
        "passport_image_library_items",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_passport_image_library_items_submission_type_created",
        "passport_image_library_items",
        ["submission_id", "image_type", "created_at"],
        unique=False,
    )

    # Reuse the existing Visa AI row IDs so durable AI-job result IDs retain a
    # stable one-to-one identity in the common library without changing 0049.
    op.execute(
        sa.text(
            """
            INSERT INTO passport_image_library_items (
                id,
                submission_id,
                image_type,
                source,
                storage_key,
                original_source_storage_key,
                content_sha256,
                prompt,
                prompt_sha256,
                model,
                created_by_user_id,
                created_at
            )
            SELECT
                id,
                submission_id,
                'visa_photo',
                'ai_generated',
                generated_storage_key,
                original_source_storage_key,
                content_sha256,
                prompt,
                prompt_sha256,
                model,
                created_by_user_id,
                created_at
            FROM passport_visa_ai_images
            ON CONFLICT (submission_id, image_type, storage_key) DO NOTHING
            """
        )
    )

    # Before the durable AI library existed, a successful Visa AI edit could
    # live only as the active edit source on the crop row. Preserve those
    # still-live variants too; the storage unique constraint keeps variants
    # already copied from passport_visa_ai_images from being duplicated.
    op.execute(
        sa.text(
            """
            INSERT INTO passport_image_library_items (
                id,
                submission_id,
                image_type,
                source,
                storage_key,
                original_source_storage_key,
                content_sha256,
                prompt,
                prompt_sha256,
                model,
                created_by_user_id,
                created_at
            )
            SELECT
                md5(
                    submission_id::text
                    || ':visa_photo:legacy-edit:'
                    || edit_source_storage_key
                )::uuid,
                submission_id,
                'visa_photo',
                'ai_generated',
                edit_source_storage_key,
                source_storage_key,
                NULL,
                NULL,
                NULL,
                'legacy-ai-edit',
                updated_by_user_id,
                updated_at
            FROM passport_image_crops
            WHERE image_type = 'visa_photo'
              AND edit_source_storage_key IS NOT NULL
              AND edit_source_storage_key <> ''
            ON CONFLICT (submission_id, image_type, storage_key) DO NOTHING
            """
        )
    )

    _backfill_original(
        image_type="passport_front",
        storage_column="image_s3_key",
        exclude_excel_placeholder=True,
    )
    _backfill_original(
        image_type="visa_photo",
        storage_column="passport_photo_s3_key",
    )
    _backfill_original(
        image_type="passport_back",
        storage_column="passport_back_s3_key",
    )


def _backfill_original(
    *,
    image_type: str,
    storage_column: str,
    exclude_excel_placeholder: bool = False,
) -> None:
    placeholder_filter = (
        f"AND {storage_column} NOT LIKE 'excel-imports/%'"
        if exclude_excel_placeholder
        else ""
    )
    # md5(text)::uuid is deterministic and available in PostgreSQL without an
    # extension. It makes this data migration safe to rerun after interruption.
    op.execute(
        sa.text(
            f"""
            INSERT INTO passport_image_library_items (
                id,
                submission_id,
                image_type,
                source,
                storage_key,
                original_source_storage_key,
                created_by_user_id,
                created_at
            )
            SELECT
                md5(id::text || ':{image_type}:original')::uuid,
                id,
                '{image_type}',
                'original',
                {storage_column},
                {storage_column},
                NULL,
                created_at
            FROM passport_submissions
            WHERE {storage_column} IS NOT NULL
              AND {storage_column} <> ''
              {placeholder_filter}
            ON CONFLICT (submission_id, image_type, storage_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_passport_image_library_items_submission_type_created",
        table_name="passport_image_library_items",
    )
    op.drop_index(
        "ix_passport_image_library_items_created_by_user_id",
        table_name="passport_image_library_items",
    )
    op.drop_index(
        "ix_passport_image_library_items_submission_id",
        table_name="passport_image_library_items",
    )
    op.drop_table("passport_image_library_items")
