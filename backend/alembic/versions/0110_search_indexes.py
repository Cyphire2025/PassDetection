"""Add bounded-build substring indexes; preserve all existing rows.

The release helper must quiesce writers before migration. These transactional
indexes take a write-blocking table lock while built (maximum120seconds); this
is not a claim of an online or zero-downtime rollout. Any timeout rolls back
both indexes and the revision. pg_trgm is a trusted PostgreSQL16 extension.
"""

from alembic import op

revision = "0110_search_indexes"
down_revision = "0109_dashboard_sessions"
branch_labels = None
depends_on = None

# Frozen expressions: do not import mutable application models in migrations.
INDEXES = (('passport_submissions', 'ix_passport_search_trgm', "lower(coalesce(client_name, '') || '\x1f' || coalesce(client_email, '') || '\x1f' || coalesce(client_phone, '') || '\x1f' || coalesce(departure_city, '') || '\x1f' || coalesce(CAST((extracted_fields ->> 'passport_number') AS VARCHAR), '') || '\x1f' || coalesce(CAST((confirmed_fields ->> 'passport_number') AS VARCHAR), '') || '\x1f' || coalesce(CAST((extracted_fields ->> 'surname') AS VARCHAR), '') || '\x1f' || coalesce(CAST((confirmed_fields ->> 'surname') AS VARCHAR), '') || '\x1f' || coalesce(CAST((extracted_fields ->> 'given_names') AS VARCHAR), '') || '\x1f' || coalesce(CAST((confirmed_fields ->> 'given_names') AS VARCHAR), ''))"), ('client_groups', 'ix_client_group_search_trgm', "lower(coalesce(name, '') || '\x1f' || coalesce(destination, ''))"))


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
    for table, name, expression in INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} USING gin (({expression}) public.gin_trgm_ops)")


def downgrade() -> None:
    for _table, name, _expression in reversed(INDEXES):
        op.drop_index(name)
    # Other indexes may also use this shared extension; never drop it here.
