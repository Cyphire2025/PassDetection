"""Add bounded server-verified Apple App Attest key state.

Revision ID: 0081_mobile_app_attest_keys
Revises: 0080_domestic_ticket_lanes

The table stores only hashes plus verifier-produced public material. It never
stores a device private key, an attestation object, a bearer token, or PII.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0081_mobile_app_attest_keys"
down_revision = "0080_domestic_ticket_lanes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mobile_app_attest_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("device_identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("key_identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("verification_material", sa.LargeBinary(), nullable=False),
        sa.Column("assertion_counter", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_asserted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(device_identifier_hash) = 64",
            name="ck_mobile_app_attest_device_hash",
        ),
        sa.CheckConstraint(
            "length(key_identifier_hash) = 64",
            name="ck_mobile_app_attest_key_hash",
        ),
        sa.CheckConstraint(
            "length(verification_material) BETWEEN 32 AND 4096",
            name="ck_mobile_app_attest_material_size",
        ),
        sa.CheckConstraint(
            "assertion_counter >= 0",
            name="ck_mobile_app_attest_counter",
        ),
        sa.CheckConstraint(
            "environment IN ('development', 'production')",
            name="ck_mobile_app_attest_environment",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_mobile_app_attest_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_mobile_app_attest_state_shape",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mobile_app_attest_account_status",
        "mobile_app_attest_keys",
        ["agency_id", "account_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_mobile_app_attest_account_device_active",
        "mobile_app_attest_keys",
        ["agency_id", "account_id", "device_identifier_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_mobile_app_attest_key_active",
        "mobile_app_attest_keys",
        ["key_identifier_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_mobile_app_attest_key_active", table_name="mobile_app_attest_keys")
    op.drop_index(
        "uq_mobile_app_attest_account_device_active",
        table_name="mobile_app_attest_keys",
    )
    op.drop_index("ix_mobile_app_attest_account_status", table_name="mobile_app_attest_keys")
    op.drop_table("mobile_app_attest_keys")
