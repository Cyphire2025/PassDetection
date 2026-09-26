"""Exercise 0109 against legacy rows inside a rolled-back PostgreSQL schema."""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [pytest.mark.service_integration,
              pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


async def test_cutover_retains_legacy_rows_and_only_revokes_dashboard_credentials():
    database = os.environ["POSTGRES_DB"]
    assert database == "test_db" or database.startswith("passdetection_ci_")
    engine = create_async_engine(URL.create(
        "postgresql+asyncpg", username=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "localhost"), port=int(os.environ.get("POSTGRES_PORT", "5432")), database=database,
    ), poolclass=NullPool)
    schema = "auth_cutover_" + uuid.uuid4().hex
    user_id, token_id, mobile_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await connection.execute(text("CREATE TABLE users (id uuid PRIMARY KEY, password_hash text, mfa_secret text)"))
                await connection.execute(text("CREATE TABLE user_security_states (user_id uuid PRIMARY KEY, session_version integer)"))
                await connection.execute(text("CREATE TABLE mobile_device_sessions (id uuid PRIMARY KEY, session_generation integer, status text)"))
                await connection.execute(text("""CREATE TABLE refresh_tokens (
                    id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id), token varchar(128),
                    session_version integer NOT NULL, created_at timestamptz NOT NULL,
                    expires_at timestamptz NOT NULL, is_revoked boolean NOT NULL, revoked_at timestamptz)"""))
                await connection.execute(text("INSERT INTO users VALUES (:id,'unchanged-password','unchanged-MFA')"), {"id": user_id})
                await connection.execute(text("INSERT INTO user_security_states VALUES (:id,7)"), {"id": user_id})
                await connection.execute(text("INSERT INTO mobile_device_sessions VALUES (:id,9,'active')"), {"id": mobile_id})
                await connection.execute(text("""INSERT INTO refresh_tokens VALUES
                    (:token,:user,'retained-keyed-digest',7,now(),now()+interval '1 day',false,NULL)"""), {"token": token_id, "user": user_id})
                original = (await connection.execute(text("SELECT id,user_id,token,expires_at FROM refresh_tokens"))).one()
                def migrate(sync_connection):
                    path = Path(__file__).parents[2] / "alembic/versions/0109_dashboard_sessions.py"
                    spec = importlib.util.spec_from_file_location("auth_cutover_qualification", path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.op = Operations(MigrationContext.configure(sync_connection))
                    module.upgrade()
                await connection.run_sync(migrate)
                assert (await connection.execute(text("SELECT id,user_id,token,expires_at FROM refresh_tokens"))).one() == original
                assert (await connection.execute(text("SELECT is_revoked,revoked_at IS NOT NULL FROM refresh_tokens"))).one() == (True, True)
                assert await connection.scalar(text("SELECT revocation_reason FROM dashboard_sessions")) == "legacy_cutover"
                assert (await connection.execute(text("SELECT password_hash,mfa_secret FROM users"))).one() == ("unchanged-password", "unchanged-MFA")
                assert await connection.scalar(text("SELECT session_version FROM user_security_states")) == 7
                assert (await connection.execute(text("SELECT session_generation,status FROM mobile_device_sessions"))).one() == (9, "active")
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
