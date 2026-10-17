"""Real PostgreSQL rehearsal using only a disposable local synthetic database."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import URL, create_engine, insert, text
from sqlalchemy.pool import NullPool

from app.infrastructure.database import model_registry  # noqa: F401
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel
from scripts.workspace_branding_release import POLICY, SOURCE, TARGET, migration_entries

ROOT = Path(__file__).resolve().parents[1]
CHECKS = {'source_upgrade', 'idempotent_target', 'lock_failure', 'historical_rows_catalog_acl_preserved',
          'wrong_baseline_rejected', 'new_columns_null', 'runtime_grants_verified', 'early_writes_rejected'}


def qualify() -> dict:
    host, database = os.environ['POSTGRES_HOST'], os.environ['POSTGRES_DB']
    if host not in {'127.0.0.1', 'localhost'} or not database.startswith('passdetection_ci_'):
        raise ValueError('isolated_local_synthetic_database_required')
    name = 'passdetection_ci_branding_' + uuid.uuid4().hex[:12]
    url = URL.create('postgresql+psycopg2', username=os.environ['POSTGRES_USER'],
                     password=os.environ['POSTGRES_PASSWORD'], host=host,
                     port=int(os.environ.get('POSTGRES_PORT', '5432')), database=database)
    admin = create_engine(url, poolclass=NullPool, isolation_level='AUTOCOMMIT')
    engine = create_engine(url.set(database=name), poolclass=NullPool)
    env = {**os.environ, 'POSTGRES_DB': name, 'MCP_RELEASE_PROOF_SHA256': 'a' * 64}
    contract = {**POLICY, 'migrations': migration_entries(ROOT)}
    created = False

    def migrate(action, target):
        result = subprocess.run([sys.executable, '-m', 'alembic', action, target], cwd=ROOT,
                                env=env, capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError('synthetic_alembic_failed')

    def invoke(*, capture=False, success=True, overrides=None):
        args = [sys.executable, 'scripts/release_workspace_branding_upgrade.py', '--contract-json', json.dumps(contract)]
        if capture:
            args.append('--capture-baseline')
        result = subprocess.run(args, cwd=ROOT, env={**env, **(overrides or {})}, capture_output=True, timeout=240)
        value = json.loads(result.stdout)
        assert (result.returncode == 0) == success, value
        assert value['automatic_downgrade'] is False
        return value

    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        created = True
        migrate('upgrade', SOURCE)
        agency, company, group = [uuid.uuid4() for _ in range(3)]
        with engine.begin() as connection:
            connection.execute(insert(AgencyModel).values(id=agency, name='Synthetic branding agency', email='branding@example.test'))
            connection.execute(insert(ClientOrganizationModel).values(id=company, agency_id=agency,
                name='Synthetic company', normalized_name='synthetic company'))
            connection.execute(insert(ClientGroupModel).values(id=group, agency_id=agency, company_id=company,
                name='Synthetic group', token=uuid.uuid4().hex))
            connection.execute(text('CREATE ROLE branding_runtime NOLOGIN'))
            connection.execute(text('GRANT USAGE ON SCHEMA public TO branding_runtime'))
            connection.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO branding_runtime'))
        baseline = invoke(capture=True)
        env['MCP_RELEASE_BASELINE_SHA256'] = baseline['preservation_sha256']
        invoke(success=False, overrides={'MCP_RELEASE_BASELINE_SHA256': 'b' * 64})
        with engine.begin() as held:
            # First column would be added before this lock blocks the second.
            # PostgreSQL must roll both additions back as one transaction.
            # SHARE permits the preservation SELECTs and blocks ALTER TABLE,
            # so the timeout happens after the first ADD COLUMN, during DDL.
            held.execute(text('LOCK TABLE client_groups IN SHARE MODE'))
            invoke(success=False)
            assert held.scalar(text('SELECT version_num FROM alembic_version')) == SOURCE
            assert held.scalar(text("SELECT count(*) FROM information_schema.columns WHERE column_name IN ('logo_image_key','banner_image_key') AND table_schema='public'")) == 0
        upgraded = invoke()
        assert upgraded['executed_revisions'] == [TARGET]
        assert upgraded['preservation_sha256'] == baseline['preservation_sha256']
        assert upgraded['new_columns_null'] is True
        assert invoke()['status'] == 'already_at_target'
        invoke(capture=True, success=False)
        with engine.begin() as connection:
            connection.execute(text('SET LOCAL ROLE branding_runtime'))
            assert connection.scalar(text('SELECT logo_image_key FROM client_organizations WHERE id=:id'), {'id': company}) is None
            assert connection.scalar(text('SELECT banner_image_key FROM client_groups WHERE id=:id'), {'id': group}) is None
            connection.execute(text("UPDATE client_organizations SET logo_image_key='synthetic/temporary' WHERE id=:id"), {'id': company})
        invoke(success=False)
        with engine.begin() as connection:
            connection.execute(text('UPDATE client_organizations SET logo_image_key=NULL WHERE id=:id'), {'id': company})
            connection.execute(text("UPDATE client_organizations SET name='Unexpected mutation' WHERE id=:id"), {'id': company})
        invoke(success=False)
        with engine.begin() as connection:
            connection.execute(text("UPDATE client_organizations SET name='Synthetic company' WHERE id=:id"), {'id': company})
            connection.execute(text('CREATE INDEX unexpected_branding_idx ON client_groups(name)'))
        invoke(success=False)
        with engine.begin() as connection:
            connection.execute(text('DROP INDEX unexpected_branding_idx'))
        assert invoke()['status'] == 'already_at_target'
        # Downgrade is exercised only in this disposable synthetic database.
        migrate('downgrade', SOURCE)
        assert invoke(capture=True)['preservation_sha256'] == baseline['preservation_sha256']
        assert invoke()['status'] == 'upgraded'
        return {'source': SOURCE, 'target': TARGET, 'checks': {key: True for key in CHECKS},
                'synthetic_only': True, 'messages_sent': 0, 'automatic_downgrade': False}
    finally:
        engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()
