"""Provision separate PostgreSQL runtime/migration roles without deleting data.

Run only as the existing database administrator during the reviewed maintenance
procedure. Credentials are read from environment, never CLI arguments or output.
DDL is transactional. An existing privileged/member runtime role is rejected,
not silently modified. This is not a backup or a production recovery proof.
"""

from __future__ import annotations

import os
import re
import sys
from contextlib import closing

import psycopg2
from psycopg2 import sql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.infrastructure.database.role_policy import RUNTIME_ROLE_QUERY, require_runtime_role
from app.infrastructure.database.model_registry import Base


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"{name} must be supplied through the protected environment")
    return value


def role_name(name: str) -> str:
    value = required(name)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value) or value.startswith("pg_"):
        raise ValueError(f"{name} must be a dedicated PostgreSQL role identifier")
    return value


def ensure_role(cursor, name: str, password: str) -> None:
    cursor.execute(
        "SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls, "
        "EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid) "
        "FROM pg_roles r WHERE rolname = %s", (name,),
    )
    existing = cursor.fetchone()
    if existing and any(existing):
        raise ValueError("An existing target role has elevated flags or memberships; use a new dedicated role")
    if not existing:
        cursor.execute(sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s"
        ).format(sql.Identifier(name)), (password,))
    # Existing credentials are deliberately not rotated. A connection check
    # below verifies the supplied secret before any ownership/grant change.


def provision(connection, runtime: str, migrator: str, runtime_password: str, migration_password: str) -> None:
    """Restrict changes to this application's public schema, inside one transaction."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, current_database()")
        administrator, database = cursor.fetchone()
        if len({administrator, runtime, migrator}) != 3:
            raise ValueError("Administrator, runtime and migration identities must be distinct")
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        if cursor.fetchone() != (True,):
            raise ValueError("Provisioning requires the existing bootstrap administrator")
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('passdetection.database-role-provisioning'))")
        cursor.execute("SELECT to_regclass('public.audit_logs'), to_regclass('public.alembic_version')")
        if not all(cursor.fetchone()):
            raise ValueError("Apply the reviewed application migrations before runtime-role provisioning")
        # No blanket REASSIGN OWNED: that can touch unrelated shared objects.
        # Refuse unexpected owners and transfer only application relations.
        cursor.execute(
            "SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m') "
            "ORDER BY CASE WHEN c.relkind='S' THEN 1 ELSE 0 END, c.relname"
        )
        relations = cursor.fetchall()
        expected_tables = set(Base.metadata.tables) | {"alembic_version"}
        observed_tables = {name for name, kind, _ in relations if kind in {"r", "p"}}
        if observed_tables != expected_tables:
            raise ValueError("Public tables differ from application metadata; review before provisioning")
        if any(kind in {"v", "m"} for _, kind, _ in relations):
            raise ValueError("Unexpected public view; review before provisioning")
        cursor.execute(
            "SELECT seq.relname FROM pg_class seq JOIN pg_namespace n ON n.oid=seq.relnamespace "
            "WHERE n.nspname='public' AND seq.relkind='S' AND NOT EXISTS ("
            "SELECT 1 FROM pg_depend d JOIN pg_class t ON t.oid=d.refobjid "
            "WHERE d.objid=seq.oid AND d.classid='pg_class'::regclass "
            "AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i') "
            "AND t.relname=ANY(%s))", (list(expected_tables),),
        )
        if cursor.fetchone():
            raise ValueError("Unexpected public sequence; review before provisioning")
        if any(owner not in {administrator, migrator} for _, _, owner in relations):
            raise ValueError("Unexpected public-schema owner; review ownership before provisioning")
        ensure_role(cursor, runtime, runtime_password)
        ensure_role(cursor, migrator, migration_password)
        kinds = {"r": "TABLE", "p": "TABLE", "S": "SEQUENCE", "v": "VIEW", "m": "MATERIALIZED VIEW"}
        for name, kind, _owner in relations:
            cursor.execute(sql.SQL("ALTER {} public.{} OWNER TO {}").format(
                sql.SQL(kinds[kind]), sql.Identifier(name), sql.Identifier(migrator)
            ))
        cursor.execute(
            "SELECT t.typname, pg_get_userbyid(t.typowner) FROM pg_type t "
            "JOIN pg_namespace n ON n.oid=t.typnamespace "
            "WHERE n.nspname='public' AND t.typtype IN ('e','d')"
        )
        for name, owner in cursor.fetchall():
            if owner not in {administrator, migrator}:
                raise ValueError("Unexpected public type owner; review before provisioning")
            cursor.execute(sql.SQL("ALTER TYPE public.{} OWNER TO {}").format(
                sql.Identifier(name), sql.Identifier(migrator)
            ))
        # This applied application trigger must remain replaceable by the
        # migration identity. Do not transfer arbitrary extension functions.
        cursor.execute(sql.SQL(
            "ALTER FUNCTION public.reject_audit_log_mutation() OWNER TO {}"
        ).format(sql.Identifier(migrator)))
        for statement in (
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(sql.Identifier(database), sql.Identifier(migrator)),
            sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(migrator)),
            sql.SQL("REVOKE CREATE ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)),
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(runtime)),
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(runtime)),
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(runtime)),
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(runtime)),
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(sql.Identifier(migrator), sql.Identifier(runtime)),
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}").format(sql.Identifier(migrator), sql.Identifier(runtime)),
        ):
            cursor.execute(statement)
        cursor.execute(sql.SQL("REVOKE ALL ON public.alembic_version FROM {}, PUBLIC").format(sql.Identifier(runtime)))
        cursor.execute(sql.SQL("GRANT SELECT ON public.alembic_version TO {}").format(sql.Identifier(runtime)))
        cursor.execute(sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON public.audit_logs FROM {}, PUBLIC").format(sql.Identifier(runtime)))
        cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(runtime)))
        cursor.execute(RUNTIME_ROLE_QUERY)
        require_runtime_role(cursor.fetchone())
        cursor.execute("RESET ROLE")


def main() -> int:
    runtime, migrator = role_name("POSTGRES_RUNTIME_USER"), role_name("POSTGRES_MIGRATION_USER")
    runtime_password = required("POSTGRES_RUNTIME_PASSWORD")
    migration_password = required("POSTGRES_MIGRATION_PASSWORD")
    if len({required("POSTGRES_PASSWORD"), runtime_password, migration_password}) != 3:
        raise ValueError("Database identities must have independent secrets")
    parameters = dict(
        host=os.environ.get("POSTGRES_HOST", "db"), port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=required("POSTGRES_DB"), user=required("POSTGRES_USER"), password=required("POSTGRES_PASSWORD"),
        connect_timeout=10,
    )
    # Verify existing-role secrets before the transaction alters ownership. New
    # roles are checked after commit because uncommitted roles cannot log in.
    with closing(psycopg2.connect(**parameters)) as connection, connection:
        with connection.cursor() as cursor:
            for name, password in ((runtime, runtime_password), (migrator, migration_password)):
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,))
                if cursor.fetchone():
                    with closing(psycopg2.connect(**{**parameters, "user": name, "password": password})):
                        pass
        provision(connection, runtime, migrator, runtime_password, migration_password)
    for name, password in ((runtime, runtime_password), (migrator, migration_password)):
        with closing(psycopg2.connect(**{**parameters, "user": name, "password": password})) as connection, connection:
            if name == runtime:
                with connection.cursor() as cursor:
                    cursor.execute(RUNTIME_ROLE_QUERY)
                    require_runtime_role(cursor.fetchone())
    print("Database roles provisioned and authenticated; application data preserved")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (psycopg2.Error, ValueError, RuntimeError):
        # Driver/DDL error details may contain a credential; do not echo them.
        print("Database role provisioning stopped; review prerequisites. No data deletion was attempted.", file=sys.stderr)
        raise SystemExit(1) from None
