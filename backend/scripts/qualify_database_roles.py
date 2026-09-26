"""Exercise role separation against an explicitly isolated synthetic database.

Requires a migrated passdetection_ci_* database. No production target is accepted.
Fixtures are retained for inspection; this script never drops databases/tables.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import psycopg2
from provision_database_roles import main as provision_roles
from provision_database_roles import provision, required
from psycopg2 import sql
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config.settings import DatabaseSettings
from app.infrastructure.database.role_policy import RUNTIME_ROLE_QUERY, require_runtime_role


@contextmanager
def connect(user: str, password: str):
    connection = psycopg2.connect(
        host=required("POSTGRES_HOST"), port=required("POSTGRES_PORT"),
        dbname=required("POSTGRES_DB"), user=user, password=password, connect_timeout=10,
    )
    try:
        with connection:
            yield connection
    finally:
        connection.close()


async def verify_async_url(settings: DatabaseSettings) -> None:
    engine = create_async_engine(settings.async_url)
    try:
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT current_user"))).scalar_one() == settings.user
    finally:
        await engine.dispose()


def main() -> int:
    if not required("POSTGRES_DB").startswith("passdetection_ci_"):
        raise ValueError("Role qualification accepts only explicitly isolated CI databases")
    fixture_id = str(uuid.uuid4())
    with connect(required("POSTGRES_USER"), required("POSTGRES_PASSWORD")) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agencies(id,name,email,created_at,updated_at) VALUES (%s,%s,%s,now(),now())",
                (fixture_id, "role qualification", fixture_id + "@example.test"),
            )
    provision_roles()
    # A retry must preserve credentials, rows, constraints and ownership.
    provision_roles()
    runtime, password = required("POSTGRES_RUNTIME_USER"), required("POSTGRES_RUNTIME_PASSWORD")
    assertions = 0
    with connect(runtime, password) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT name FROM agencies WHERE id=%s", (fixture_id,))
            assert cursor.fetchone() == ("role qualification",)
            assertions += 1
            cursor.execute("UPDATE agencies SET name='runtime CRUD verified' WHERE id=%s", (fixture_id,))
            cursor.execute("SELECT name FROM agencies WHERE id=%s", (fixture_id,))
            assert cursor.fetchone() == ("runtime CRUD verified",)
            assertions += 1
            cursor.execute(
                "INSERT INTO audit_logs(id,action,entity_type,created_at) VALUES (%s,'qualification','synthetic',now())",
                (str(uuid.uuid4()),),
            )
            assertions += 1
    forbidden = (
        "CREATE TABLE public.forbidden_qualification(id integer)",
        "ALTER TABLE public.agencies ADD COLUMN forbidden_qualification integer",
        "ALTER TABLE public.audit_logs DISABLE TRIGGER ALL",
        "UPDATE public.audit_logs SET action='forbidden' WHERE false",
        "DELETE FROM public.audit_logs WHERE false",
        "TRUNCATE public.audit_logs",
        "UPDATE public.alembic_version SET version_num='forbidden' WHERE false",
        "CREATE ROLE forbidden_qualification",
    )
    for statement in forbidden:
        with connect(runtime, password) as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(statement)
                except psycopg2.errors.InsufficientPrivilege:
                    connection.rollback()
                    assertions += 1
                else:
                    connection.rollback()
                    raise AssertionError("Runtime operation unexpectedly allowed: " + statement)
    with connect(runtime, password) as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(required("POSTGRES_MIGRATION_USER"))))
            except psycopg2.errors.InsufficientPrivilege:
                connection.rollback()
                assertions += 1
            else:
                raise AssertionError("Runtime can assume migration identity")
    with connect(required("POSTGRES_MIGRATION_USER"), required("POSTGRES_MIGRATION_PASSWORD")) as connection:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE public.agencies ADD COLUMN qualification_rolled_back integer")
            connection.rollback()  # Test schema authority without retaining a schema difference.
            assertions += 1
    settings = DatabaseSettings(
        _env_file=None, host=required("POSTGRES_HOST"), port=int(required("POSTGRES_PORT")),
        db=required("POSTGRES_DB"), user=runtime, password=password,
    )
    engine = create_engine(settings.sync_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar_one() == runtime
    finally:
        engine.dispose()
    asyncio.run(verify_async_url(settings))
    assertions += 2
    with connect(required("POSTGRES_USER"), required("POSTGRES_PASSWORD")) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE public.unrelated_secret(value text)")
            cursor.execute("INSERT INTO public.unrelated_secret VALUES ('synthetic non-application data')")
            try:
                provision(connection, runtime, required("POSTGRES_MIGRATION_USER"), password,
                          required("POSTGRES_MIGRATION_PASSWORD"))
            except ValueError as error:
                assert "Public tables differ" in str(error)
                assertions += 1
            else:
                raise AssertionError("Provisioning accepted an unrelated public relation")
            connection.rollback()  # Removes only the uncommitted qualification fixture.
    for table, column in (("alembic_version", "version_num"), ("audit_logs", "action")):
        with connect(required("POSTGRES_USER"), required("POSTGRES_PASSWORD")) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("GRANT UPDATE ({}) ON public.{} TO {}").format(
                    sql.Identifier(column), sql.Identifier(table), sql.Identifier(runtime)
                ))
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(runtime)))
                cursor.execute(RUNTIME_ROLE_QUERY)
                try:
                    require_runtime_role(cursor.fetchone())
                except RuntimeError:
                    assertions += 1
                else:
                    raise AssertionError("Column-only protected write privilege escaped the guard")
                connection.rollback()  # Do not retain the deliberately insecure grant.
    print(f"PASS: {assertions} PostgreSQL role/row-preservation/DSN assertions; idempotent provisioning verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
