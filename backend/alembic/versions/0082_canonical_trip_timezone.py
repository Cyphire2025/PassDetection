"""Add the canonical IANA timezone owned by each client group.

Revision ID: 0082_canonical_trip_timezone
Revises: 0081_mobile_app_attest_keys

Existing and rolling-deployment writes use the established Asia/Kolkata
countdown default. Application/domain validation accepts only identifiers that
the installed IANA timezone database can resolve.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0082_canonical_trip_timezone"
down_revision = "0081_mobile_app_attest_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Kolkata'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_client_groups_timezone_shape",
        "client_groups",
        "length(timezone) BETWEEN 1 AND 64 AND timezone = trim(timezone)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_client_groups_timezone_shape",
        "client_groups",
        type_="check",
    )
    op.drop_column("client_groups", "timezone")
