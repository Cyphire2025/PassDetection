"""Bounded operational impact and commit-ordered company change publication.

DDL is frozen, application-independent. These new feature tables have no legacy
backfill. Rollback refuses durable operations history rather than dropping it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0133_traveller_document_impact"
down_revision = "0132_traveller_source_seek"
branch_labels = None
depends_on = None

DDL = (
    "CREATE TABLE traveller_change_feeds (\n\tcompany_id UUID NOT NULL, \n\tagency_id UUID NOT NULL, \n\tlast_sequence BIGINT DEFAULT '0' NOT NULL, \n\tPRIMARY KEY (company_id), \n\tCONSTRAINT fk_traveller_change_feed_company_scope FOREIGN KEY(company_id, agency_id) REFERENCES client_organizations (id, agency_id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_traveller_feed_sequence CHECK (last_sequence >= 0)\n)",
    "CREATE TABLE traveller_document_review_tasks (\n\tevent_id UUID NOT NULL, \n\tparticipation_id UUID NOT NULL, \n\told_document_revision_id UUID NOT NULL, \n\tnew_document_revision_id UUID, \n\texpected_participation_revision INTEGER NOT NULL, \n\treason_code VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(16) DEFAULT 'pending' NOT NULL, \n\trevision INTEGER DEFAULT '1' NOT NULL, \n\tresolution_reason VARCHAR(500), \n\tresolved_by_user_id UUID, \n\tresolved_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tagency_id UUID NOT NULL, \n\tcompany_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_traveller_document_review_task_company_scope FOREIGN KEY(company_id, agency_id) REFERENCES client_organizations (id, agency_id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_traveller_review_event_scope FOREIGN KEY(event_id, agency_id, company_id) REFERENCES traveller_change_events (id, agency_id, company_id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_traveller_review_participation_scope FOREIGN KEY(participation_id, agency_id, company_id) REFERENCES traveller_participations (id, agency_id, company_id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_traveller_review_old_document_scope FOREIGN KEY(old_document_revision_id, agency_id, company_id) REFERENCES traveller_document_revisions (id, agency_id, company_id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_traveller_review_new_document_scope FOREIGN KEY(new_document_revision_id, agency_id, company_id) REFERENCES traveller_document_revisions (id, agency_id, company_id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_traveller_review_event_participation UNIQUE (event_id, participation_id), \n\tCONSTRAINT ck_traveller_review_status CHECK (status IN ('pending','resolved','dismissed')), \n\tCONSTRAINT ck_traveller_review_revisions CHECK (revision >= 1 AND expected_participation_revision >= 1), \n\tCONSTRAINT ck_traveller_review_resolution CHECK (status = 'pending' OR (resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL AND resolution_reason IS NOT NULL)), \n\tFOREIGN KEY(resolved_by_user_id) REFERENCES users (id) ON DELETE RESTRICT\n)",
    'CREATE INDEX ix_traveller_review_participation ON traveller_document_review_tasks (participation_id, status, id)',
    'CREATE INDEX ix_traveller_review_queue ON traveller_document_review_tasks (agency_id, company_id, status, created_at, id)',
    "CREATE INDEX ix_traveller_change_impact_queue ON traveller_change_events (impact_available_at, id) WHERE processed_at IS NULL AND impact_attempt_count < 5 AND event_type IN ('document_promoted', 'document_blocked')",
    'CREATE INDEX ix_traveller_change_unpublished ON traveller_change_events (feed_sequence, created_at, id)',
    'CREATE INDEX ix_traveller_change_unpublished_scope ON traveller_change_events (agency_id, company_id, created_at, id) WHERE feed_sequence IS NULL',
    'CREATE INDEX ix_traveller_participation_person_seek ON traveller_participations (agency_id, company_id, traveller_id, id)',
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("traveller_change_events", sa.Column("feed_sequence", sa.BigInteger(), nullable=True))
    op.add_column("traveller_change_events", sa.Column("impact_cursor", sa.UUID(), nullable=True))
    op.add_column("traveller_change_events", sa.Column("impact_attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("traveller_change_events", sa.Column("impact_available_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
    op.add_column("traveller_change_events", sa.Column("impact_error_code", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_traveller_change_event_scope", "traveller_change_events", ["id", "agency_id", "company_id"])
    op.create_unique_constraint("uq_traveller_change_feed_sequence", "traveller_change_events", ["agency_id", "company_id", "feed_sequence"])
    op.create_check_constraint("ck_traveller_change_processing_counts", "traveller_change_events", "impact_attempt_count >= 0 AND (feed_sequence IS NULL OR feed_sequence > 0)")
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM traveller_document_review_tasks) OR EXISTS (SELECT 1 FROM traveller_change_feeds)")):
        raise RuntimeError("Operational history exists; disable consumers instead of dropping retained records.")
    op.drop_table("traveller_document_review_tasks")
    op.drop_table("traveller_change_feeds")
    op.drop_index("ix_traveller_participation_person_seek", table_name="traveller_participations")
    for name in ("ix_traveller_change_unpublished", "ix_traveller_change_unpublished_scope", "ix_traveller_change_impact_queue"):
        op.drop_index(name, table_name="traveller_change_events")
    for name in ("uq_traveller_change_event_scope", "uq_traveller_change_feed_sequence"):
        op.drop_constraint(name, "traveller_change_events", type_="unique")
    op.drop_constraint("ck_traveller_change_processing_counts", "traveller_change_events", type_="check")
    for column in ("impact_error_code", "impact_available_at", "impact_attempt_count", "impact_cursor", "feed_sequence"):
        op.drop_column("traveller_change_events", column)
