"""Replace deterministic attendance QR tokens with expiring random tokens.

Revision ID: 0014_secure_qr_tokens
Revises: 0013_auth_hardening
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_secure_qr_tokens"
down_revision = "0013_auth_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "passenger_qr_tokens",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Existing rows were derived from predictable UUID5 payloads. They must never
    # remain scannable after this migration; users explicitly generate secure replacements.
    op.execute(
        """
        UPDATE passenger_qr_tokens
        SET is_active = false,
            revoked_at = COALESCE(revoked_at, now()),
            expires_at = now(),
            updated_at = now()
        """
    )
    op.alter_column("passenger_qr_tokens", "expires_at", nullable=False)
    op.create_index(
        op.f("ix_passenger_qr_tokens_expires_at"),
        "passenger_qr_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_passenger_qr_tokens_expires_at"), table_name="passenger_qr_tokens")
    op.drop_column("passenger_qr_tokens", "expires_at")
