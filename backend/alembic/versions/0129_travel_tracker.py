"""Persist group-scoped manual visa and flight readiness."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0129_travel_tracker"
down_revision = "0128_mcp_document_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "travel_tracker",
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visa_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flight_booked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("visa_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flight_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "visa_updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "flight_updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["passenger_id", "agency_id", "group_id"],
            [
                "passport_submissions.id",
                "passport_submissions.agency_id",
                "passport_submissions.group_id",
            ],
            name="fk_travel_tracker_passenger_scope",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_travel_tracker_group_marks",
        "travel_tracker",
        ["agency_id", "group_id", "visa_applied", "flight_booked"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE travel_tracker IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM travel_tracker)")).scalar_one():
        raise RuntimeError(
            "Export and clear tracker records before downgrading to preserve readiness history."
        )
    op.drop_table("travel_tracker")
