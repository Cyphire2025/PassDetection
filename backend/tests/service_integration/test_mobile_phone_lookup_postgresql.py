"""Actual 0096 migration and planner proof using only a temporary synthetic table."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import URL, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.infrastructure.database.models import PassportSubmissionModel
from app.presentation.api.v1.routes.mobile_auth_phone_support import phone_digits_predicate

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]

INDEX = "ix_passport_submissions_mobile_phone_lookup"


async def test_submitted_phone_migration_and_custom_and_generic_plans_use_index():
    # This explicitly gated test never touches a persistent application table.
    # The session-local table shadows the same name until this connection ends.
    database = os.environ.get("FCM_TEST_POSTGRES_DB", "")
    if not database.startswith(("passdetection_ci_", "passdetection_fcm_test_")):
        pytest.fail("FCM_TEST_POSTGRES_DB must explicitly name an isolated test database")
    if database == os.environ.get("POSTGRES_DB"):
        pytest.fail("The explicitly named test database must differ from application POSTGRES_DB")
    url = URL.create(
        "postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=database,
    )
    engine = create_async_engine(
        url, poolclass=NullPool, echo=False,
        connect_args={"server_settings": {"lock_timeout": "5000", "statement_timeout": "15000"}},
    )
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0096_mobile_phone_lookup.py"
    spec = importlib.util.spec_from_file_location("mobile_phone_lookup_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == database
            # The actual ORM binds status as this native enum. Keep its test
            # equivalent session-local as well; no persistent app type exists
            # or is needed in the explicitly isolated empty test database.
            await connection.execute(text("CREATE TYPE pg_temp.submission_status_enum AS ENUM ('submitted')"))
            await connection.execute(text("""CREATE TEMP TABLE passport_submissions (
                id uuid PRIMARY KEY, client_phone varchar(32), status pg_temp.submission_status_enum,
                client_reviewed_at timestamptz) ON COMMIT DROP"""))
            await connection.execute(text("""INSERT INTO passport_submissions
                SELECT md5(i::text)::uuid, '+91 ' || (9000000000::bigint + i)::text,
                    'submitted', now() FROM generate_series(1, 20000) AS i"""))

            def upgrade(sync_connection):
                migration.op = Operations(MigrationContext.configure(sync_connection))
                migration.upgrade()

            await connection.run_sync(upgrade)
            await connection.execute(text("ANALYZE passport_submissions"))
            statement = (
                select(PassportSubmissionModel.id)
                .where(
                    phone_digits_predicate("+919000012345"),
                    PassportSubmissionModel.client_reviewed_at.is_not(None),
                    PassportSubmissionModel.status == "submitted",
                )
                .order_by(PassportSubmissionModel.id).limit(101)
            )
            assert len((await connection.execute(statement)).all()) == 1
            sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            plan = await connection.scalar(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"))
            assert INDEX in json.dumps(plan)

            await connection.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))
            await connection.execute(text(r"""PREPARE mobile_phone_index_probe(text[]) AS
                SELECT id FROM passport_submissions
                WHERE regexp_replace(coalesce(client_phone, ''), '\D', '', 'g') = ANY($1)
                  AND client_reviewed_at IS NOT NULL AND status = 'submitted'
                ORDER BY id LIMIT 101"""))
            generic_plan = await connection.scalar(text("""EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                EXECUTE mobile_phone_index_probe(ARRAY['919000012345', '00919000012345', '9000012345'])"""))
            assert INDEX in json.dumps(generic_plan)
            assert await connection.scalar(text("SELECT count(*) FROM passport_submissions")) == 20000
            print("MOBILE_PHONE_INDEX_PROOF=" + json.dumps({
                "index": INDEX, "synthetic_rows": 20000,
                "actual_orm_query_matches": 1,
                "custom_plan_uses_index": True, "generic_plan_uses_index": True,
            }))
    finally:
        await engine.dispose()
