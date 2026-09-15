"""Retain FCM acceptance and uncertain outcomes without inventing delivery.

Revision ID: 0095_mobile_fcm_delivery
Revises: 0094_whatsapp_receipt_inbox

Only check constraints change. Existing rows, columns and indexes are retained.
"""

from alembic import op
import sqlalchemy as sa

revision = "0095_mobile_fcm_delivery"
down_revision = "0094_whatsapp_receipt_inbox"
branch_labels = None
depends_on = None

_TABLE = "mobile_push_deliveries"
_OLD_STATES = "'submitting', 'retry', 'receipt_pending', 'delivered', 'failed', 'cancelled'"


def _constraints(*, fcm: bool) -> None:
    states = _OLD_STATES + (", 'provider_accepted', 'unknown'" if fcm else "")
    receipt_states = "'receipt_pending', 'delivered'" + (", 'provider_accepted'" if fcm else "")
    op.drop_constraint("ck_mobile_push_delivery_status", _TABLE, type_="check")
    op.create_check_constraint("ck_mobile_push_delivery_status", _TABLE, f"status IN ({states})")
    op.drop_constraint("ck_mobile_push_delivery_receipt_shape", _TABLE, type_="check")
    op.create_check_constraint(
        "ck_mobile_push_delivery_receipt_shape",
        _TABLE,
        f"status NOT IN ({receipt_states}) OR provider_ticket_id IS NOT NULL",
    )


def upgrade() -> None:
    _constraints(fcm=True)


def downgrade() -> None:
    # Never coerce accepted/uncertain outcomes or erase their history to roll back.
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM mobile_push_deliveries "
            "WHERE status IN ('provider_accepted', 'unknown'))"
        )
    ):
        raise RuntimeError("FCM delivery history requires schema 0095; downgrade refused")
    _constraints(fcm=False)
