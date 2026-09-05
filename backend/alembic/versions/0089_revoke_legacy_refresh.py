"""Revoke legacy plaintext refresh credentials without changing current sessions.

Revision ID: 0089_revoke_legacy_refresh
Revises: 0088_merge_my_photos_hardening
"""

from alembic import op

revision = "0089_revoke_legacy_refresh"
down_revision = "0088_merge_my_photos_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Current keyed SHA-256 rows are exactly 64 lowercase hexadecimal bytes.
    # Unknown historical formats must sign in again, never receive a fallback.
    op.execute(
        "UPDATE refresh_tokens SET is_revoked = TRUE, "
        "revoked_at = CURRENT_TIMESTAMP "
        "WHERE is_revoked = FALSE AND token !~ '^[0-9a-f]{64}$'"
    )


def downgrade() -> None:
    # Credential revocation is irreversible; rollback must not revive sessions.
    pass
