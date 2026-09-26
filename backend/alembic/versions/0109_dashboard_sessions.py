"""Bind dashboard refresh credentials to durable revocable session families.

Revision ID: 0109_dashboard_sessions
Revises: 0108_data_invariants

Existing rows are preserved as revoked tombstones, not inferred lineage.
One dashboard sign-in is required after cutover. Users, passwords, MFA and
native mobile session tables/generations are untouched.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0109_dashboard_sessions"
down_revision = "0108_data_invariants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    op.create_table(
        "dashboard_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.String(32)),
        sa.UniqueConstraint("id", "user_id", name="uq_dashboard_session_user"),
    )
    op.create_index("ix_dashboard_sessions_user_id", "dashboard_sessions", ["user_id"])
    op.add_column("refresh_tokens", sa.Column("session_id", postgresql.UUID(as_uuid=True)))
    op.execute("""INSERT INTO dashboard_sessions
        (id, user_id, session_version, created_at, expires_at, revoked_at, revocation_reason)
        SELECT id, user_id, session_version, created_at, expires_at,
               COALESCE(revoked_at, CURRENT_TIMESTAMP), 'legacy_cutover'
        FROM refresh_tokens""")
    op.execute("UPDATE refresh_tokens SET session_id = id, is_revoked = true, "
               "revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)")
    op.alter_column("refresh_tokens", "session_id", nullable=False)
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_foreign_key("fk_refresh_token_session_user", "refresh_tokens", "dashboard_sessions",
                          ["session_id", "user_id"], ["id", "user_id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_constraint("fk_refresh_token_session_user", "refresh_tokens", type_="foreignkey")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "session_id")
    op.drop_index("ix_dashboard_sessions_user_id", table_name="dashboard_sessions")
    op.drop_table("dashboard_sessions")
