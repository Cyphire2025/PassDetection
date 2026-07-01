"""passport confidence score

Revision ID: 0004_passport_confidence_score
Revises: 0003_client_review_submission
Create Date: 2026-06-29 19:15:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_passport_confidence_score"
down_revision = "0003_client_review_submission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "passport_submissions",
        sa.Column("confidence_score", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("passport_submissions", "confidence_score")
