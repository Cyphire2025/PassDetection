"""Synthetic populated 0129 fixture; called only after the CI database guard."""

from __future__ import annotations

import secrets
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

from scripts.rehearse_postgresql_upgrade import (
    IDS,
    _connect,
    _replace_database,
    database_environment,
)

COMPANY_ID = "e0000000-0000-0000-0000-000000000001"
BROADCAST_ID = "e0000000-0000-0000-0000-000000000002"
RUNTIME_ROLE_SQL = """
    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='passdetection_ci_companies_runtime') THEN
        CREATE ROLE passdetection_ci_companies_runtime NOLOGIN;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='passdetection_ci_companies_runtime'
          AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Synthetic runtime role has unexpected authority';
      END IF;
    END $$;
"""


@contextmanager
def migration_owner(environment: Mapping[str, str]) -> Iterator[dict[str, str]]:
    """Create a unique restricted owner; callers must drop owned databases first."""
    role = "passdetection_ci_companies_owner_" + secrets.token_hex(6)
    password = secrets.token_urlsafe(32)
    connection = _connect(environment, "postgres")
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %s").format(sql.Identifier(role)), (password,))
            cursor.execute(RUNTIME_ROLE_SQL)
        connection.commit()
    finally:
        connection.close()
    try:
        yield {**environment, "POSTGRES_USER": role, "POSTGRES_PASSWORD": password,
            "PGUSER": role, "PGPASSWORD": password}
    finally:
        connection = _connect(environment, "postgres")
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            connection.commit()
        finally:
            connection.close()


def replace_owned_database(admin: Mapping[str, str], owner: Mapping[str, str], name: str) -> dict[str, str]:
    """Only the cluster administrator creates databases; the owner cannot."""
    _replace_database(admin, name)  # Validates the exact disposable database prefix.
    connection = _connect(admin, "postgres")
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(name), sql.Identifier(owner["POSTGRES_USER"])))
        connection.commit()
    finally:
        connection.close()
    return database_environment(owner, name)


def seed_company_and_roster(connection: Connection) -> None:
    """700 durable source people, one delivery phone; no retained identity data."""
    parameters = {**IDS, "company": COMPANY_ID, "broadcast": BROADCAST_ID}
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO client_organizations (id, agency_id, name, normalized_name, status)
            VALUES (%(company)s, %(agency_a)s, 'Synthetic company', 'synthetic company', 'active');
            UPDATE gc_group_access SET client_organization_id = %(company)s WHERE id = %(gc_access_a)s;
            INSERT INTO passport_submissions
              (id, group_id, agency_id, client_name, image_s3_key, status, confirmed_fields, created_at, updated_at)
            VALUES ('40000000-0000-0000-0000-000000000002', %(group_a)s, %(agency_a)s,
              'Synthetic second person', 'ci-only/second.jpg', 'confirmed',
              '{"passport_number":"CI0000002"}'::jsonb, now(), now());
            INSERT INTO whatsapp_broadcast_groups
              (id, agency_id, name, organizing_company_name, created_at, updated_at)
            VALUES (%(broadcast)s, %(agency_a)s, 'Synthetic 700-person roster', 'Synthetic company', now(), now());
            INSERT INTO client_group_whatsapp_broadcast_links
              (id, client_group_id, broadcast_group_id, agency_id, created_at)
            VALUES ('e0000000-0000-0000-0000-000000000003', %(group_a)s, %(broadcast)s, %(agency_a)s, now());
            INSERT INTO whatsapp_broadcast_recipients
              (id, broadcast_group_id, agency_id, name, phone_number, normalized_phone_number,
               imported_fields, display_order, created_at)
            VALUES ('e0000000-0000-0000-0000-000000000004', %(broadcast)s, %(agency_a)s,
              'Synthetic person 0', '+919999999999', '+919999999999', '{"staff_code":"0000"}', 1, now());
            INSERT INTO whatsapp_broadcast_rejected_contacts
              (id, broadcast_group_id, agency_id, source_file_name, sheet_name, row_number,
               raw_name, raw_phone_number, imported_fields, display_order, reason_code, reason, fingerprint, created_at)
            SELECT md5('ci-companies-roster-' || n)::uuid, %(broadcast)s, %(agency_a)s,
              'synthetic-700.xlsx', 'People', n + 2, 'Synthetic person ' || n, '+919999999999',
              jsonb_build_object('staff_code', lpad(n::text, 4, '0')), n + 1,
              'duplicate_phone', 'Distinct person sharing one delivery phone', lpad(n::text, 64, '0'), now()
            FROM generate_series(1, 699) n;
            GRANT USAGE ON SCHEMA public TO passdetection_ci_companies_runtime;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO passdetection_ci_companies_runtime;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO passdetection_ci_companies_runtime;
        """, parameters)
    connection.commit()


def create_interrupted_source_index(connection: Connection) -> None:
    """A real concurrent uniqueness failure leaves an invalid index to repair.

    This uses two synthetic passports in the same agency. Never write pg_catalog
    to fabricate an invalid state: PostgreSQL itself must produce that state.
    """
    connection.rollback()
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute("CREATE UNIQUE INDEX CONCURRENTLY ix_passport_submissions_scoped_seek "
                    "ON passport_submissions (agency_id)")
            except psycopg2.errors.UniqueViolation:
                pass
            else:
                raise AssertionError("Synthetic concurrent index build unexpectedly succeeded")
            cursor.execute("SELECT indisvalid FROM pg_index WHERE indexrelid="
                "'public.ix_passport_submissions_scoped_seek'::regclass")
            if cursor.fetchone() != (False,):
                raise AssertionError("Concurrent failure did not leave the expected invalid index")
    finally:
        connection.autocommit = False
