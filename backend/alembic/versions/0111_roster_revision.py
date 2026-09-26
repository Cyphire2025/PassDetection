"""Transactional roster cache invalidation; no business-row rewriting.

Statement transition tables coalesce a bulk mutation to one revision increment
per affected group. Group updates change NEW in a BEFORE trigger, never recurse.
"""

from alembic import op
import sqlalchemy as sa

revision = "0111_roster_revision"
down_revision = "0110_search_indexes"
branch_labels = None
depends_on = None

TABLES = ("passport_submissions", "manager_group_access", "coordinator_assignments", "coordinator_group_assignments")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("client_groups", sa.Column("roster_revision", sa.BigInteger(), nullable=False, server_default="0"))
    op.execute("""CREATE FUNCTION bump_group_roster_revision() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN NEW.roster_revision := OLD.roster_revision + 1; RETURN NEW; END $$""")
    op.execute("""CREATE TRIGGER group_roster_revision BEFORE UPDATE ON client_groups
        FOR EACH ROW EXECUTE FUNCTION bump_group_roster_revision()""")
    for event, source in (("insert", "SELECT group_id FROM new_roster_rows"),
                          ("delete", "SELECT group_id FROM old_roster_rows"),
                          ("update", "SELECT group_id FROM old_roster_rows UNION SELECT group_id FROM new_roster_rows")):
        op.execute(f"""CREATE FUNCTION bump_roster_after_{event}() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE affected uuid;
            BEGIN
                FOR affected IN SELECT DISTINCT group_id FROM ({source}) changed ORDER BY group_id LOOP
                    UPDATE client_groups SET roster_revision = roster_revision + 1 WHERE id = affected;
                END LOOP;
                RETURN NULL;
            END $$""")
        references = "NEW TABLE AS new_roster_rows" if event == "insert" else "OLD TABLE AS old_roster_rows"
        if event == "update":
            references += " NEW TABLE AS new_roster_rows"
        for table in TABLES:
            op.execute(f"""CREATE TRIGGER roster_revision_{event} AFTER {event.upper()} ON {table}
                REFERENCING {references} FOR EACH STATEMENT EXECUTE FUNCTION bump_roster_after_{event}()""")


def downgrade() -> None:
    for table in TABLES:
        for event in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER roster_revision_{event} ON {table}")
    for event in ("insert", "update", "delete"):
        op.execute(f"DROP FUNCTION bump_roster_after_{event}()")
    op.execute("DROP TRIGGER group_roster_revision ON client_groups")
    op.execute("DROP FUNCTION bump_group_roster_revision()")
    op.drop_column("client_groups", "roster_revision")
