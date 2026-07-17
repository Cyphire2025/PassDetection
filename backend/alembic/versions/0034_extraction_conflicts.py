"""Add non-destructive passport extraction conflict review metadata.

Revision ID: 0034_extraction_conflicts
Revises: 0033_passport_capture_fields
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0034_extraction_conflicts"
down_revision = "0033_passport_capture_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "passport_submissions",
        sa.Column(
            "extraction_conflicts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("passport_submissions", "extraction_conflicts")
