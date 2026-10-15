"""Add isolated expiring public drafts; no existing business rows are modified."""
import sqlalchemy as sa
from alembic import op

revision = "0136_returning_drafts"
down_revision = "0135_company_removal_history"
branch_labels = None
depends_on = None

DDL = ('CREATE TABLE traveller_returning_drafts (\n'
 '\tgroup_id UUID NOT NULL, \n'
 '\tmode VARCHAR(16) NOT NULL, \n'
 '\tupload_session_hash VARCHAR(64), \n'
 '\ttraveller_id UUID, \n'
 '\tpassport_id UUID, \n'
 '\tdocument_revision_id UUID, \n'
 '\tsecret_hash VARCHAR(64) NOT NULL, \n'
 '\tstatus VARCHAR(16) NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tfields_revision INTEGER NOT NULL, \n'
 '\tpayload_ciphertext TEXT NOT NULL, \n'
 '\trequirements_ciphertext TEXT, \n'
 '\treview_version VARCHAR(64) NOT NULL, \n'
 '\tlast_save_key VARCHAR(128), \n'
 '\tlast_save_digest VARCHAR(64), \n'
 '\tverified_contact_claim_id UUID, \n'
 '\tverified_phone_ciphertext TEXT, \n'
 '\tverified_phone_fingerprint VARCHAR(64), \n'
 '\tphone_verified_at TIMESTAMP WITH TIME ZONE, \n'
 '\tcontact_revision INTEGER NOT NULL, \n'
 '\tprofile_revision INTEGER NOT NULL, \n'
 '\tauthorization_version INTEGER NOT NULL, \n'
 '\tcompletion_key VARCHAR(128), \n'
 '\tcompletion_digest VARCHAR(64), \n'
 '\tparticipation_id UUID, \n'
 '\tsource_submission_id UUID, \n'
 '\tresult_status VARCHAR(16), \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tagency_id UUID NOT NULL, \n'
 '\tcompany_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_returning_draft_company_scope FOREIGN KEY(company_id, agency_id) REFERENCES '
 'client_organizations (id, agency_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_returning_draft_group_scope FOREIGN KEY(group_id, agency_id) REFERENCES client_groups '
 '(id, agency_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_returning_draft_document_scope FOREIGN KEY(document_revision_id, passport_id, '
 'traveller_id, agency_id, company_id) REFERENCES traveller_document_revisions (id, passport_id, '
 'traveller_id, agency_id, company_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_returning_draft_scope UNIQUE (id, agency_id, company_id), \n'
 '\tCONSTRAINT uq_returning_draft_secret UNIQUE (secret_hash), \n'
 '\tCONSTRAINT uq_returning_draft_tenant UNIQUE (id, agency_id), \n'
 "\tCONSTRAINT ck_returning_draft_mode CHECK (mode IN ('returning','fresh')), \n"
 "\tCONSTRAINT ck_returning_draft_authority CHECK ((mode = 'returning' AND company_id IS NOT NULL AND "
 'traveller_id IS NOT NULL AND passport_id IS NOT NULL AND document_revision_id IS NOT NULL) OR (mode = '
 "'fresh' AND traveller_id IS NULL AND passport_id IS NULL AND document_revision_id IS NULL AND "
 'upload_session_hash IS NOT NULL)), \n'
 "\tCONSTRAINT ck_returning_draft_status CHECK (status IN ('active','submitted','expired')), \n"
 '\tCONSTRAINT ck_returning_draft_revision CHECK (revision >= 1 AND fields_revision >= 1), \n'
 '\tCONSTRAINT ck_returning_draft_expiry CHECK (expires_at > created_at)\n'
 ')',
 'CREATE INDEX ix_returning_draft_expiry ON traveller_returning_drafts (status, expires_at, id)',
 'CREATE TABLE traveller_draft_assets (\n'
 '\tdraft_id UUID NOT NULL, \n'
 '\tside VARCHAR(16) NOT NULL, \n'
 '\tobject_key VARCHAR(512) NOT NULL, \n'
 '\tchecksum VARCHAR(64) NOT NULL, \n'
 '\tbyte_size INTEGER NOT NULL, \n'
 '\tcontent_type VARCHAR(64) NOT NULL, \n'
 '\tidempotency_key VARCHAR(128) NOT NULL, \n'
 '\tstate VARCHAR(16) NOT NULL, \n'
 '\tis_current BOOLEAN NOT NULL, \n'
 '\texpected_revision INTEGER NOT NULL, \n'
 '\tfields_revision INTEGER NOT NULL, \n'
 '\textraction_status VARCHAR(16) NOT NULL, \n'
 '\textraction_ciphertext TEXT, \n'
 '\tclassification_ciphertext TEXT, \n'
 '\tattempts INTEGER NOT NULL, \n'
 '\tavailable_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tlease_expires_at TIMESTAMP WITH TIME ZONE, \n'
 '\tid UUID NOT NULL, \n'
 '\tagency_id UUID NOT NULL, \n'
 '\tcompany_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_returning_asset_draft_scope FOREIGN KEY(draft_id, agency_id, company_id) REFERENCES '
 'traveller_returning_drafts (id, agency_id, company_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_returning_asset_draft_tenant FOREIGN KEY(draft_id, agency_id) REFERENCES '
 'traveller_returning_drafts (id, agency_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_returning_asset_scope UNIQUE (id, agency_id, company_id), \n'
 '\tCONSTRAINT uq_returning_asset_request UNIQUE (draft_id, idempotency_key), \n'
 "\tCONSTRAINT ck_returning_asset_side CHECK (side IN ('front','back','cover','back_cover','photo')), \n"
 '\tCONSTRAINT ck_returning_asset_state CHECK (state IN '
 "('uploading','ready','discarded','adopted','purged')), \n"
 '\tCONSTRAINT ck_returning_asset_extraction CHECK (extraction_status IN '
 "('none','pending','running','succeeded','failed')), \n"
 '\tCONSTRAINT ck_returning_asset_budget CHECK (byte_size > 0 AND byte_size <= 10485760 AND attempts >= '
 '0)\n'
 ')',
 'CREATE INDEX ix_returning_asset_cleanup ON traveller_draft_assets (state, created_at, id)',
 'CREATE INDEX ix_returning_asset_extraction ON traveller_draft_assets (extraction_status, '
 'available_at, id)',
 'CREATE UNIQUE INDEX uq_returning_asset_current ON traveller_draft_assets (draft_id, side) WHERE '
 'is_current',
 'CREATE TABLE traveller_draft_contact_proofs (\n'
 '\tdraft_id UUID NOT NULL, \n'
 '\temail_hash VARCHAR(64) NOT NULL, \n'
 '\tphone_ciphertext TEXT NOT NULL, \n'
 '\tphone_fingerprint VARCHAR(64) NOT NULL, \n'
 '\tcode_hash VARCHAR(64), \n'
 '\tstatus VARCHAR(16) NOT NULL, \n'
 '\tattempt_count INTEGER NOT NULL, \n'
 '\tmax_attempts INTEGER NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tresend_available_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tverified_at TIMESTAMP WITH TIME ZONE, \n'
 '\tproof_expires_at TIMESTAMP WITH TIME ZONE, \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tagency_id UUID NOT NULL, \n'
 '\tcompany_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_draft_contact_company_owner FOREIGN KEY(draft_id, agency_id, company_id) REFERENCES '
 'traveller_returning_drafts (id, agency_id, company_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_draft_contact_owner FOREIGN KEY(draft_id, agency_id) REFERENCES '
 'traveller_returning_drafts (id, agency_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_draft_contact_owner UNIQUE (draft_id), \n'
 '\tCONSTRAINT ck_draft_contact_status CHECK (status IN '
 "('sending','pending','failed','locked','verified','consumed')), \n"
 '\tCONSTRAINT ck_draft_contact_attempts CHECK (attempt_count >= 0 AND max_attempts > 0)\n'
 ')')


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '90s'")
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM traveller_returning_drafts)")):
        raise RuntimeError("Draft or publication receipts exist; refuse destructive rollback.")
    op.drop_table("traveller_draft_contact_proofs")
    op.drop_table("traveller_draft_assets")
    op.drop_table("traveller_returning_drafts")
