"""Serialize active mobile OTP challenges per normalized phone hash.

Revision ID: 0073_mobile_otp_single_pending_challenge
Revises: 0072_gc_mobile_passenger_session_identities
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0073_mobile_otp_single_pending_challenge"
down_revision = "0072_gc_mobile_passenger_session_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical versions allowed a resend to create another pending row while
    # the previous challenge was still unexpired. Retain only the newest row so
    # the database can become the final concurrency arbiter safely.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY phone_lookup_hash
                       ORDER BY created_at DESC, id DESC
                   ) AS pending_rank
              FROM mobile_otp_challenges
             WHERE status = 'pending'
        )
        UPDATE mobile_otp_challenges AS challenge
           SET status = 'cancelled',
               updated_at = CURRENT_TIMESTAMP
          FROM ranked
         WHERE challenge.id = ranked.id
           AND ranked.pending_rank > 1
        """
    )
    # Keep OTP requests writable while PostgreSQL verifies the partial unique
    # index. A duplicate racing the build makes the migration fail closed and
    # safely retryable instead of installing an incomplete guard.
    with op.get_context().autocommit_block():
        op.create_index(
            "uq_mobile_otp_pending_phone",
            "mobile_otp_challenges",
            ["phone_lookup_hash"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "uq_mobile_otp_pending_phone",
            table_name="mobile_otp_challenges",
            postgresql_concurrently=True,
        )
