"""Persist passenger QR payloads for office reprint views.

Revision ID: 0020_qr_payloads
Revises: 0019_rooming_checkins
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_qr_payloads"
down_revision = "0019_rooming_checkins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("passenger_qr_tokens", sa.Column("qr_payload", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("passenger_qr_tokens", "qr_payload")
