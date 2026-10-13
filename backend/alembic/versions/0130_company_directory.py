"""Promote existing company ownership to the core group without changing UUIDs.

Existing GC assignments are exact, tenant-constrained references. No name-based
inference is performed. Unassigned groups remain NULL and can be edited later.
Run the company-assignment audit before and after migration; invalid old GC
references fail the new FK instead of being silently reassigned or discarded.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0130_company_directory"
down_revision = "0129_travel_tracker"
branch_labels = None
depends_on = None


def _backfill_company_scope() -> None:
    # 0111 increments roster_revision on every group UPDATE. This additive
    # backfill must retain that old value; company_revision records new scope.
    # Earlier ADD COLUMN holds ACCESS EXCLUSIVE until the same transaction ends.
    # Refuse an unexpected trigger rather than silently suppress its behavior.
    expected_trigger = op.get_bind().scalar(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgrelid = 'public.client_groups'::regclass
              AND tgname = 'group_roster_revision' AND NOT tgisinternal
              AND tgenabled = 'O' AND tgtype = 19 AND tgnargs = 0
              AND tgqual IS NULL AND tgattr::text = ''
              AND tgfoid = 'public.bump_group_roster_revision()'::regprocedure
        )
    """))
    if expected_trigger is not True:
        raise RuntimeError("Expected enabled group roster trigger is required for company backfill")
    op.execute("ALTER TABLE public.client_groups DISABLE TRIGGER group_roster_revision")
    # Any error rolls back the revision transaction, including DISABLE. Do not
    # try to execute ENABLE inside an already-aborted PostgreSQL transaction.
    op.execute("""
        UPDATE client_groups AS g SET company_id = a.client_organization_id, company_revision = 1
        FROM gc_group_access AS a
        JOIN client_organizations AS c ON c.id = a.client_organization_id AND c.agency_id = a.agency_id
        WHERE g.id = a.group_id AND g.agency_id = a.agency_id AND g.company_id IS NULL
    """)
    op.execute("ALTER TABLE public.client_groups ENABLE TRIGGER group_roster_revision")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("client_organizations", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("client_groups", sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("client_groups", sa.Column("company_revision", sa.Integer(), nullable=False, server_default="0"))
    op.create_foreign_key("fk_client_groups_company_scope", "client_groups", "client_organizations",
                          ["company_id", "agency_id"], ["id", "agency_id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_client_groups_company_scope", "client_groups", ["id", "agency_id", "company_id"])
    _backfill_company_scope()
    op.create_foreign_key("fk_gc_group_canonical_company", "gc_group_access", "client_groups",
                          ["group_id", "agency_id", "client_organization_id"], ["id", "agency_id", "company_id"],
                          deferrable=True, initially="DEFERRED")
    op.create_index("ix_client_groups_company_seek", "client_groups", ["agency_id", "company_id", "created_at", "id"])
    op.create_index("ix_client_groups_company_lifecycle", "client_groups",
                    ["agency_id", "company_id", "status", "created_at", "id"])
    op.create_index("ix_client_org_directory_seek", "client_organizations", ["agency_id", "status", "normalized_name", "id"])
    op.create_index("ix_client_org_directory_all_seek", "client_organizations", ["agency_id", "normalized_name", "id"])
    op.create_index("ix_client_org_search_trgm", "client_organizations", ["normalized_name"],
                    postgresql_using="gin", postgresql_ops={"normalized_name": "gin_trgm_ops"})


def downgrade() -> None:
    # Company assignments made without GC App cannot be represented by the old
    # schema. Refuse a destructive rollback; export/reconcile explicitly first.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM client_groups g WHERE g.company_id IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM gc_group_access a WHERE a.group_id = g.id AND a.agency_id = g.agency_id
              AND a.client_organization_id = g.company_id
            )
          ) THEN RAISE EXCEPTION 'Rollback would discard core company assignments; reconcile first'; END IF;
        END $$;
    """)
    op.drop_index("ix_client_org_search_trgm", table_name="client_organizations")
    op.drop_index("ix_client_org_directory_all_seek", table_name="client_organizations")
    op.drop_index("ix_client_org_directory_seek", table_name="client_organizations")
    op.drop_index("ix_client_groups_company_seek", table_name="client_groups")
    op.drop_index("ix_client_groups_company_lifecycle", table_name="client_groups")
    op.drop_constraint("fk_gc_group_canonical_company", "gc_group_access", type_="foreignkey")
    op.drop_constraint("uq_client_groups_company_scope", "client_groups", type_="unique")
    op.drop_constraint("fk_client_groups_company_scope", "client_groups", type_="foreignkey")
    op.drop_column("client_groups", "company_revision")
    op.drop_column("client_groups", "company_id")
    op.drop_column("client_organizations", "revision")
