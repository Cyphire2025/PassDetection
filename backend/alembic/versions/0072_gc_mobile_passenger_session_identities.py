"""Persist the exact passenger identities proven for a mobile session.

Revision ID: 0072_gc_mobile_passenger_session_identities
Revises: 0071_gc_mobile_passenger_scope_constraints
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0072_gc_mobile_passenger_session_identities"
down_revision = "0071_gc_mobile_passenger_scope_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mobile_device_sessions",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE mobile_device_sessions
           SET account_id = COALESCE(passenger_identity_id, user_id)
         WHERE account_id IS NULL
        """
    )
    # A validated CHECK lets PostgreSQL prove SET NOT NULL without rescanning
    # the table while holding the stronger ALTER TABLE lock.
    op.create_check_constraint(
        "ck_mobile_device_sessions_account_id_not_null",
        "mobile_device_sessions",
        "account_id IS NOT NULL",
        postgresql_not_valid=True,
    )
    op.execute(
        """
        ALTER TABLE mobile_device_sessions
        VALIDATE CONSTRAINT ck_mobile_device_sessions_account_id_not_null
        """
    )
    op.alter_column(
        "mobile_device_sessions",
        "account_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_constraint(
        "ck_mobile_device_sessions_account_id_not_null",
        "mobile_device_sessions",
        type_="check",
    )

    op.create_table(
        "mobile_passenger_session_identities",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gc_group_access_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_claim_generation", sa.Integer(), nullable=False),
        sa.Column(
            "authorized_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "identity_claim_generation >= 0",
            name="ck_mobile_passenger_session_identity_generation",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_passenger_session_identity_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "passenger_identity_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
            ],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_mobile_passenger_session_identity_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "session_id",
            "passenger_identity_id",
            name="pk_mobile_passenger_session_identities",
        ),
    )
    op.create_index(
        "ix_mobile_passenger_session_identity_group",
        "mobile_passenger_session_identities",
        ["session_id", "group_id"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_passenger_session_identity_identity",
        "mobile_passenger_session_identities",
        ["passenger_identity_id", "session_id"],
        unique=False,
    )

    # Preserve only already-valid singleton passenger sessions. Any malformed
    # historical session intentionally receives no authorization row and will
    # fail closed on its next authenticated request.
    op.execute(
        """
        INSERT INTO mobile_passenger_session_identities (
            session_id,
            passenger_identity_id,
            agency_id,
            group_id,
            gc_group_access_id,
            identity_claim_generation,
            authorized_at
        )
        SELECT
            session.id,
            identity.id,
            identity.agency_id,
            identity.group_id,
            identity.gc_group_access_id,
            identity.claim_generation,
            session.created_at
          FROM mobile_device_sessions AS session
          JOIN mobile_passenger_identities AS identity
            ON identity.id = session.passenger_identity_id
           AND identity.agency_id = session.agency_id
           AND identity.gc_group_access_id = session.selected_gc_group_access_id
           AND identity.group_id = session.selected_group_id
         WHERE session.subject_role = 'passenger'
        ON CONFLICT (session_id, passenger_identity_id) DO NOTHING
        """
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_mobile_session_account",
            "mobile_device_sessions",
            ["agency_id", "account_id"],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_mobile_passenger_session_identity_identity",
        table_name="mobile_passenger_session_identities",
    )
    op.drop_index(
        "ix_mobile_passenger_session_identity_group",
        table_name="mobile_passenger_session_identities",
    )
    op.drop_table("mobile_passenger_session_identities")
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_mobile_session_account",
            table_name="mobile_device_sessions",
            postgresql_concurrently=True,
        )
    op.drop_column("mobile_device_sessions", "account_id")
