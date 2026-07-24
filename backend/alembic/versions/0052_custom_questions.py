"""Add configurable upload questions and submission answer snapshots.

Revision ID: 0052_custom_questions
Revises: 0051_exports_replacements
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0052_custom_questions"
down_revision = "0051_exports_replacements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column(
            "custom_questions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column(
            "custom_answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("passport_submissions", "custom_answers")
    op.drop_column("client_groups", "custom_questions")
