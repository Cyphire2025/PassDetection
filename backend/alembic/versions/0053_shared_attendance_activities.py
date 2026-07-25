"""Share attendance activities across every coordinator assigned to a group.

Revision ID: 0053_shared_attendance
Revises: 0052_custom_questions
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0053_shared_attendance"
down_revision = "0052_custom_questions"
branch_labels = None
depends_on = None

_ACTIVE_ACTIVITY_RANKING = """
    SELECT
        id,
        first_value(id) OVER (
            PARTITION BY group_id, normalized_name
            ORDER BY
                CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                created_at,
                id
        ) AS canonical_id
    FROM attendance_sessions
    WHERE status IN ('draft', 'active')
"""


def upgrade() -> None:
    op.add_column(
        "attendance_sessions",
        sa.Column("normalized_name", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "attendance_sessions",
        sa.Column("canonical_session_id", sa.UUID(), nullable=True),
    )
    op.execute(
        """
        UPDATE attendance_sessions
        SET
            normalized_name = lower(
                regexp_replace(btrim(name), '[[:space:]]+', ' ', 'g')
            ),
            canonical_session_id = id
        """
    )

    # Older releases created one active/draft session per coordinator. Preserve
    # every session, status, and attendance record exactly as stored. Aliases
    # point at one stable canonical row; completed historical sessions remain
    # self-canonical so a later activity with the same name stays independent.
    op.execute(
        f"""
        WITH ranked AS ({_ACTIVE_ACTIVITY_RANKING})
        UPDATE attendance_sessions AS attendance_session
        SET canonical_session_id = ranked.canonical_id
        FROM ranked
        WHERE attendance_session.id = ranked.id
        """
    )

    op.alter_column(
        "attendance_sessions",
        "normalized_name",
        existing_type=sa.String(length=160),
        nullable=False,
    )
    op.alter_column(
        "attendance_sessions",
        "canonical_session_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_attendance_sessions_canonical_session_id",
        "attendance_sessions",
        "attendance_sessions",
        ["canonical_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_attendance_sessions_canonical_session_id",
        "attendance_sessions",
        ["canonical_session_id"],
    )
    op.create_index(
        "uq_attendance_sessions_active_group_name",
        "attendance_sessions",
        ["group_id", "normalized_name"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('draft', 'active') AND id = canonical_session_id"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_attendance_sessions_active_group_name",
        table_name="attendance_sessions",
    )
    op.drop_index(
        "ix_attendance_sessions_canonical_session_id",
        table_name="attendance_sessions",
    )
    op.drop_constraint(
        "fk_attendance_sessions_canonical_session_id",
        "attendance_sessions",
        type_="foreignkey",
    )
    op.drop_column("attendance_sessions", "canonical_session_id")
    op.drop_column("attendance_sessions", "normalized_name")
