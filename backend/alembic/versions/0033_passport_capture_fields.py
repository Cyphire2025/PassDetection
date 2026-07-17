"""Add passport capture options and reliable extraction state.

Revision ID: 0033_passport_capture_fields
Revises: 0032_whatsapp_status_time
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0033_passport_capture_fields"
down_revision = "0032_whatsapp_status_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column(
            "allow_files_from_device",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "client_groups",
        sa.Column(
            "ask_nearest_domestic_airport",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.add_column(
        "passport_submissions",
        sa.Column("nearest_domestic_airport", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "passport_submissions",
        sa.Column(
            "acquisition_mode",
            sa.String(length=16),
            nullable=False,
            server_default="file",
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column("upload_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "passport_submissions",
        sa.Column(
            "extraction_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column(
            "extraction_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_unique_constraint(
        "uq_passport_submissions_group_upload_key",
        "passport_submissions",
        ["group_id", "upload_idempotency_key"],
    )
    op.create_check_constraint(
        "ck_passport_submissions_acquisition_mode",
        "passport_submissions",
        "acquisition_mode IN ('camera', 'file')",
    )
    op.create_check_constraint(
        "ck_passport_submissions_extraction_status",
        "passport_submissions",
        "extraction_status IN ("
        "'not_started', 'processing', 'extraction_complete', "
        "'extraction_partial', 'extraction_failed', 'ready_for_review'"
        ")",
    )
    op.create_check_constraint(
        "ck_passport_submissions_extraction_revision",
        "passport_submissions",
        "extraction_revision >= 0",
    )

    # Give existing submissions a meaningful extraction state rather than
    # presenting completed historical records as newly uploaded work.
    op.execute(
        """
        UPDATE passport_submissions
        SET extraction_status = CASE
            WHEN status = 'processing' THEN 'processing'
            WHEN status = 'failed' THEN 'extraction_failed'
            WHEN status IN ('review_required', 'client_submitted', 'confirmed')
                THEN 'ready_for_review'
            ELSE 'not_started'
        END
        """
    )

    op.add_column(
        "passport_processing_jobs",
        sa.Column(
            "extraction_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_passport_processing_jobs_extraction_revision",
        "passport_processing_jobs",
        "extraction_revision >= 0",
    )
    # Older deployments may already contain duplicate active jobs. Keep only
    # the newest active row before enforcing retry idempotency.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY submission_id, extraction_revision
                       ORDER BY created_at DESC, id DESC
                   ) AS row_number
            FROM passport_processing_jobs
            WHERE status IN ('queued', 'running')
        )
        UPDATE passport_processing_jobs AS jobs
        SET status = 'cancelled',
            current_stage = 'superseded',
            cancel_requested = true,
            finished_at = COALESCE(finished_at, now()),
            updated_at = now()
        FROM ranked
        WHERE jobs.id = ranked.id
          AND ranked.row_number > 1
        """
    )
    op.create_index(
        "uq_passport_processing_jobs_active_revision",
        "passport_processing_jobs",
        ["submission_id", "extraction_revision"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_passport_processing_jobs_active_revision",
        table_name="passport_processing_jobs",
    )
    op.drop_constraint(
        "ck_passport_processing_jobs_extraction_revision",
        "passport_processing_jobs",
        type_="check",
    )
    op.drop_column("passport_processing_jobs", "extraction_revision")

    op.drop_constraint(
        "ck_passport_submissions_extraction_revision",
        "passport_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_passport_submissions_extraction_status",
        "passport_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_passport_submissions_acquisition_mode",
        "passport_submissions",
        type_="check",
    )
    op.drop_constraint(
        "uq_passport_submissions_group_upload_key",
        "passport_submissions",
        type_="unique",
    )
    op.drop_column("passport_submissions", "extraction_revision")
    op.drop_column("passport_submissions", "extraction_status")
    op.drop_column("passport_submissions", "upload_idempotency_key")
    op.drop_column("passport_submissions", "acquisition_mode")
    op.drop_column("passport_submissions", "nearest_domestic_airport")

    op.drop_column("client_groups", "ask_nearest_domestic_airport")
    op.drop_column("client_groups", "allow_files_from_device")
