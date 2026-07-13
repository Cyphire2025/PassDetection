"""Add hotel check-in control records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019_rooming_checkins"
down_revision = "0018_rooming_room_vip_tag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rooming_checkins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hotel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rooming_hotels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rooming_rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checked_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("checked_in_at", sa.DateTime(timezone=True)),
        sa.Column("key_issued", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("key_issued_at", sa.DateTime(timezone=True)),
        sa.Column("welcome_letter_issued", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("welcome_letter_issued_at", sa.DateTime(timezone=True)),
        sa.Column("remarks", sa.Text()),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_checkins_hotel_passenger"),
    )
    op.create_index("ix_rooming_checkins_hotel_status", "rooming_checkins", ["hotel_id", "checked_in", "key_issued", "welcome_letter_issued"])
    op.create_index("ix_rooming_checkins_agency_id", "rooming_checkins", ["agency_id"])
    op.create_index("ix_rooming_checkins_hotel_id", "rooming_checkins", ["hotel_id"])
    op.create_index("ix_rooming_checkins_room_id", "rooming_checkins", ["room_id"])
    op.create_index("ix_rooming_checkins_passenger_id", "rooming_checkins", ["passenger_id"])


def downgrade() -> None:
    op.drop_table("rooming_checkins")
