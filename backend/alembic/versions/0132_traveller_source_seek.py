"""Build the bounded historical-source seek index without blocking writers.

Concurrent index creation can leave an invalid index after interruption. Retry
removes only that invalid index, then rebuilds it. A valid existing definition
must exactly match the intended columns before the migration can complete.
"""

import sqlalchemy as sa
from alembic import op

revision = "0132_traveller_source_seek"
down_revision = "0131_traveller_reuse"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_passport_submissions_scoped_seek"
INDEXES = (
    (INDEX_NAME, "passport_submissions", "agency_id, group_id, id"),
    ("ix_whatsapp_recipient_source_seek", "whatsapp_broadcast_recipients", "broadcast_group_id, id"),
    ("ix_whatsapp_rejected_source_seek", "whatsapp_broadcast_rejected_contacts", "broadcast_group_id, id"),
)


def upgrade() -> None:
    # Isolated revision: autocommit never commits other schema mutations.
    with op.get_context().autocommit_block():
        for name, table, columns in INDEXES:
            _ensure_index(name, table, columns)


def _ensure_index(name: str, table: str, columns: str) -> None:
    existing = op.get_bind().execute(sa.text("""
            SELECT i.indisvalid, pg_get_indexdef(i.indexrelid) AS definition
              FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relname = :name AND n.nspname = current_schema()
    """), {"name": name}).mappings().first()
    if existing is not None:
        if existing["indisvalid"]:
            expected = f"USING btree ({columns})"
            if expected not in existing["definition"] or table not in existing["definition"]:
                raise RuntimeError("Existing source seek index has an unexpected definition.")
            return
        op.execute(f"DROP INDEX CONCURRENTLY {name}")
    op.execute(f"CREATE INDEX CONCURRENTLY {name} ON {table} ({columns})")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _, _ in reversed(INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
