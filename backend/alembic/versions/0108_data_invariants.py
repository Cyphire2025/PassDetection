"""Enforce passport tenant ownership and standalone ECR domains without rewriting data.

Revision ID: 0108_data_invariants
Revises: 0107_passport_ecr_checks

Existing invalid rows abort the transaction with a count and constraint name.
No automatic reassignment, deletion or state coercion is permitted. Reconcile
the specific records separately before retrying. Values are frozen here so
future application vocabulary changes cannot change this historical migration.
"""

from alembic import op

revision = "0108_data_invariants"
down_revision = "0107_passport_ecr_checks"
branch_labels = None
depends_on = None

CHECKS = (
    ("ecr_batches", "ck_ecr_batch_status",
     "status IN ('uploading','queued','processing','completed','completed_with_errors')"),
    ("ecr_items", "ck_ecr_item_status",
     "status IN ('queued','processing','completed','failed')"),
    ("ecr_items", "ck_ecr_item_result",
     "result IS NULL OR result IN ('ECR','NA','NEEDS_REVIEW')"),
    ("ecr_items", "ck_ecr_item_counters",
     "input_tokens >= 0 AND output_tokens >= 0 AND attempts >= 0"),
    ("ecr_items", "ck_ecr_item_outcome",
     "(status = 'completed' AND result IS NOT NULL) OR "
     "(status <> 'completed' AND result IS NULL)"),
)


def _assert_no_rows(query: str, label: str) -> None:
    # Identifiers and SQL fragments are migration constants, never request data.
    op.execute(f"""DO $$ DECLARE invalid_count bigint; BEGIN
        SELECT count(*) INTO invalid_count FROM ({query}) invalid_rows;
        IF invalid_count > 0 THEN
            RAISE EXCEPTION '0108 preflight: % invalid rows violate {label}. '
                'No records were changed; reconcile ownership/state before retrying.', invalid_count;
        END IF;
    END $$""")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    _assert_no_rows(
        "SELECT p.id FROM passport_submissions p LEFT JOIN client_groups g "
        "ON (g.id = p.group_id AND g.agency_id = p.agency_id) WHERE g.id IS NULL",
        "fk_passport_submissions_group_agency",
    )
    for table, name, expression in CHECKS:
        _assert_no_rows(f"SELECT id FROM {table} WHERE NOT ({expression})", name)

    # NOT VALID starts enforcement for new writes immediately. Validation then
    # proves retained rows without rewriting the table. A concurrent bad write
    # cannot slip past validation; any failure rolls back this whole migration.
    op.execute("ALTER TABLE passport_submissions ADD CONSTRAINT "
               "fk_passport_submissions_group_agency FOREIGN KEY (group_id, agency_id) "
               "REFERENCES client_groups (id, agency_id) ON DELETE RESTRICT NOT VALID")
    for table, name, expression in CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
    op.execute("ALTER TABLE passport_submissions VALIDATE CONSTRAINT "
               "fk_passport_submissions_group_agency")
    for table, name, _ in CHECKS:
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    # Removing only additive constraints preserves every row and column.
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
    op.drop_constraint("fk_passport_submissions_group_agency", "passport_submissions",
                       type_="foreignkey")
