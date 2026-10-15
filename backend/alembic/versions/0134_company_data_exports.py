"""Durable company export jobs and bounded All data seek indexes."""

import sqlalchemy as sa
from alembic import op

revision = "0134_company_data_exports"
down_revision = "0133_traveller_document_impact"
branch_labels = None
depends_on = None

SOURCE_CHRONOLOGY_BACKFILL = """
UPDATE traveller_match_cases AS match
SET source_created_at = source.created_at
FROM passport_submissions AS source
WHERE match.source_kind = 'passport_submission'
  AND match.source_created_at IS NULL
  AND match.agency_id = source.agency_id
  AND match.group_id = source.group_id
  AND source.id = CASE
    WHEN match.source_row_key ~ '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$'
    THEN match.source_row_key::uuid
    ELSE NULL
  END
"""

DDL = ('CREATE TABLE company_data_export_jobs (\n'
 '\trequested_by_user_id UUID NOT NULL, \n'
 '\tkind VARCHAR(16) NOT NULL, \n'
 "\tstatus VARCHAR(16) DEFAULT 'queued' NOT NULL, \n"
 '\tidempotency_key VARCHAR(128) NOT NULL, \n'
 '\tcompany_revision INTEGER NOT NULL, \n'
 "\tphase VARCHAR(24) DEFAULT 'people' NOT NULL, \n"
 '\tcursor UUID, \n'
 "\tprocessed_count INTEGER DEFAULT '0' NOT NULL, \n"
 "\tpart_count INTEGER DEFAULT '0' NOT NULL, \n"
 "\tattempt_count INTEGER DEFAULT '0' NOT NULL, \n"
 '\tavailable_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n'
 '\tlease_expires_at TIMESTAMP WITH TIME ZONE, \n'
 '\tlease_token UUID, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcompleted_at TIMESTAMP WITH TIME ZONE, \n'
 '\tlast_error_code VARCHAR(64), \n'
 '\tid UUID NOT NULL, \n'
 '\tagency_id UUID NOT NULL, \n'
 '\tcompany_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_company_data_export_company_scope FOREIGN KEY(company_id, agency_id) REFERENCES '
 'client_organizations (id, agency_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_company_data_export_scope UNIQUE (id, agency_id, company_id), \n'
 '\tCONSTRAINT uq_company_export_request UNIQUE (agency_id, company_id, requested_by_user_id, '
 'idempotency_key), \n'
 "\tCONSTRAINT ck_company_export_kind CHECK (kind IN ('excel','images')), \n"
 '\tCONSTRAINT ck_company_export_status CHECK (status IN '
 "('queued','running','succeeded','failed','cancelled','expired')), \n"
 '\tCONSTRAINT ck_company_export_counts CHECK (processed_count >= 0 AND part_count >= 0 AND attempt_count >= '
 '0), \n'
 '\tCONSTRAINT ck_company_export_company_revision CHECK (company_revision >= 1), \n'
 '\tCONSTRAINT ck_company_export_phase CHECK (phase IN '
 "('people','retained_images','source_front','source_back','source_cover','source_back_cover','source_photo','finalize')), \n"
 '\tFOREIGN KEY(requested_by_user_id) REFERENCES users (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_company_export_expiry ON company_data_export_jobs (expires_at, status, id)',
 'CREATE INDEX ix_company_export_queue ON company_data_export_jobs (status, available_at, id)',
 'CREATE INDEX ix_company_export_scope ON company_data_export_jobs (agency_id, company_id, '
 'requested_by_user_id, created_at, id)',
 'CREATE TABLE company_data_export_parts (\n'
 '\tjob_id UUID NOT NULL, \n'
 '\tpart_number INTEGER NOT NULL, \n'
 '\tpart_kind VARCHAR(16) NOT NULL, \n'
 '\tobject_key VARCHAR(1024) NOT NULL, \n'
 '\tcontent_type VARCHAR(128) NOT NULL, \n'
 '\tbyte_size INTEGER NOT NULL, \n'
 '\tcontent_sha256 VARCHAR(64) NOT NULL, \n'
 '\trecord_count INTEGER NOT NULL, \n'
 '\tpurged_at TIMESTAMP WITH TIME ZONE, \n'
 '\tid UUID NOT NULL, \n'
 '\tagency_id UUID NOT NULL, \n'
 '\tcompany_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_company_export_part_job FOREIGN KEY(job_id, agency_id, company_id) REFERENCES '
 'company_data_export_jobs (id, agency_id, company_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_company_export_part_number UNIQUE (job_id, part_number), \n'
 '\tCONSTRAINT ck_company_export_part_shape CHECK (part_number >= 1 AND byte_size > 0 AND record_count >= '
 '0), \n'
 "\tCONSTRAINT ck_company_export_part_kind CHECK (part_kind IN ('rows','images','workbook'))\n"
 ')',
 'CREATE INDEX ix_company_export_part_scope ON company_data_export_parts (agency_id, company_id, job_id, '
 'part_number)',
 'CREATE INDEX ix_traveller_document_person_seek ON traveller_document_revisions (agency_id, company_id, '
 'traveller_id, created_at, id)',
 'CREATE INDEX ix_traveller_asset_company_seek ON traveller_document_assets (agency_id, company_id, id)',
 'CREATE INDEX ix_traveller_profile_created_seek ON traveller_profiles (agency_id, company_id, created_at, '
 'id)',
 'CREATE INDEX ix_traveller_match_person_source ON traveller_match_cases (agency_id, company_id, '
 'traveller_id, status, source_kind, source_created_at, id)',
 'CREATE INDEX ix_company_export_live_lease ON company_data_export_jobs (lease_expires_at) WHERE lease_expires_at IS NOT NULL',
 "CREATE INDEX ix_traveller_reconciliation_advance ON traveller_reconciliation_jobs (available_at, id) WHERE status = 'succeeded' AND last_error_code = 'chain_advance_pending'",
 "CREATE INDEX ix_company_export_pending_scope ON company_data_export_jobs (agency_id, company_id, id) WHERE status IN ('queued','running')",
 "CREATE INDEX ix_company_export_cleanup ON company_data_export_jobs (expires_at, id) WHERE status != 'expired'",
 "CREATE INDEX ix_company_export_part_unpurged ON company_data_export_parts (job_id, id) WHERE purged_at IS NULL")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '90s'")
    op.add_column("traveller_match_cases", sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text(SOURCE_CHRONOLOGY_BACKFILL))
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM company_data_export_jobs)")):
        raise RuntimeError("Export history exists; retain the job receipts instead of dropping them.")
    op.drop_table("company_data_export_parts")
    op.drop_table("company_data_export_jobs")
    op.drop_index('ix_traveller_profile_created_seek')
    op.drop_index('ix_traveller_document_person_seek')
    op.drop_index('ix_traveller_asset_company_seek')
    op.drop_index('ix_traveller_match_person_source')
    op.drop_column('traveller_match_cases', 'source_created_at')
    op.drop_index('ix_traveller_reconciliation_advance')
