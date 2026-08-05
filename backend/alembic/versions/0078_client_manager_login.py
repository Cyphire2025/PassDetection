"""Make direct-password Client Manager accounts immediately usable.

Revision ID: 0078_client_manager_login
Revises: 0077_gc_app_admin_list
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0078_client_manager_login"
down_revision = "0077_gc_app_admin_list"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "client_manager_profiles",
        "force_password_change",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
    )
    # Password-created accounts have no invitation-token pair. Repair only
    # those records; genuine token invitations must still be redeemed.
    op.execute(
        sa.text(
            """
            UPDATE client_manager_profiles
               SET status = CASE
                       WHEN status = 'invited'
                        AND invitation_token_hash IS NULL
                        AND invitation_expires_at IS NULL
                       THEN 'active'
                       ELSE status
                   END,
                   activated_at = CASE
                       WHEN status = 'invited'
                        AND invitation_token_hash IS NULL
                        AND invitation_expires_at IS NULL
                       THEN COALESCE(activated_at, CURRENT_TIMESTAMP)
                       ELSE activated_at
                   END,
                   force_password_change = false,
                   access_generation = access_generation + 1,
                   revision = revision + 1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE force_password_change IS true
                OR (
                    status = 'invited'
                    AND invitation_token_hash IS NULL
                    AND invitation_expires_at IS NULL
                    AND deleted_at IS NULL
                )
            """
        )
    )


def downgrade() -> None:
    # The repaired account statuses represent legitimate usable accounts and
    # must not be made inaccessible during a rollback.
    op.alter_column(
        "client_manager_profiles",
        "force_password_change",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("true"),
    )
