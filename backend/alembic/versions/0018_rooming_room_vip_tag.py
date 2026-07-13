"""Allow VIP room allocation tags."""

from __future__ import annotations

from alembic import op


revision = "0018_rooming_room_vip_tag"
down_revision = "0017_rooming_room_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_rooming_rooms_tag", "rooming_rooms", type_="check")
    op.create_check_constraint(
        "ck_rooming_rooms_tag",
        "rooming_rooms",
        "allocation_tag IN ('mixed', 'male', 'female', 'family', 'couple', 'vip')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_rooming_rooms_tag", "rooming_rooms", type_="check")
    op.create_check_constraint(
        "ck_rooming_rooms_tag",
        "rooming_rooms",
        "allocation_tag IN ('mixed', 'male', 'female', 'family', 'couple')",
    )
