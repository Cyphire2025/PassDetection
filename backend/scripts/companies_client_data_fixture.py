"""Synthetic retained identity and manager history for the 0133 upgrade rehearsal."""
from psycopg2.extensions import connection as Connection

from scripts.companies_rehearsal_fixture import COMPANY_ID
from scripts.rehearse_postgresql_upgrade import IDS


def seed_retained_history(connection: Connection) -> None:
    parameters = {**IDS, "company": COMPANY_ID}
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO traveller_profiles (id, agency_id, company_id, status,
              display_name_ciphertext, reuse_permission_status, reuse_permission_evidence)
            VALUES ('f0000000-0000-0000-0000-000000000001', %(agency_a)s, %(company)s,
              'active', 'synthetic-retained-encrypted-name', 'unknown', '{"synthetic":true}');
            INSERT INTO traveller_passports (id, agency_id, company_id, traveller_id,
              issuing_country, document_type, number_fingerprint, fingerprint_key_version,
              number_ciphertext, status, is_default)
            VALUES ('f0000000-0000-0000-0000-000000000002', %(agency_a)s, %(company)s,
              'f0000000-0000-0000-0000-000000000001', 'IND', 'P', repeat('a',64),
              'synthetic', 'synthetic-retained-encrypted-passport', 'accepted', true);
            INSERT INTO traveller_document_revisions (id, agency_id, company_id, traveller_id,
              passport_id, revision_number, status, fields_ciphertext, source_provenance,
              reliable_fields, date_of_birth, expiry_date, source_submission_id, source_group_id,
              accepted_at, idempotency_key)
            SELECT md5('ci-retained-version-' || n)::uuid, %(agency_a)s, %(company)s,
              'f0000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000002',
              n, 'accepted', 'synthetic-encrypted-version-' || n, '{"synthetic":true}',
              '["passport_number","date_of_birth","expiry_date"]', '1990-01-01', '2032-01-01',
              %(passenger_a)s, %(group_a)s, now(), 'synthetic-version-' || n
            FROM generate_series(1,3) n;
            INSERT INTO client_manager_profiles (id, agency_id, user_id, organization_id,
              normalized_phone_number, status, activated_at)
            VALUES ('f0000000-0000-0000-0000-000000000003', %(agency_a)s, %(admin_a)s,
              %(company)s, '+919999999998', 'active', now());
            INSERT INTO client_manager_group_assignments (id, agency_id, organization_id,
              group_id, profile_id, gc_group_access_id, is_active)
            VALUES ('f0000000-0000-0000-0000-000000000004', %(agency_a)s, %(company)s,
              %(group_a)s, 'f0000000-0000-0000-0000-000000000003', %(gc_access_a)s, true);
            INSERT INTO traveller_match_cases (id, agency_id, company_id, group_id,
              traveller_id, source_kind, source_row_key, status, reason_code, evidence)
            SELECT md5('ci-source-date-' || n)::uuid, %(agency_a)s, %(company)s,
              %(group_a)s, 'f0000000-0000-0000-0000-000000000001', 'passport_submission',
              CASE n WHEN 1 THEN %(passenger_a)s WHEN 2 THEN 'invalid-uuid-source'
                     ELSE '40000000-0000-0000-0000-000000000099' END,
              'resolved', 'synthetic-history', '{"synthetic":true}'
            FROM generate_series(1,3) n;
        """, parameters)
    connection.commit()


def verify_detached_manager_constraints(connection: Connection) -> None:
    """Exercise actual PostgreSQL constraints; rollback every synthetic mutation."""
    import psycopg2

    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE client_manager_group_assignments SET organization_id=NULL, "
                "is_active=false, revoked_at=now() WHERE id='f0000000-0000-0000-0000-000000000004'")
            cursor.execute("SAVEPOINT detached_manager")
            attempts = (
                ("UPDATE client_manager_group_assignments SET is_active=true, revoked_at=NULL "
                 "WHERE id='f0000000-0000-0000-0000-000000000004'", psycopg2.errors.CheckViolation),
                ("UPDATE client_manager_group_assignments SET agency_id='10000000-0000-0000-0000-000000000002' "
                 "WHERE id='f0000000-0000-0000-0000-000000000004'", psycopg2.errors.ForeignKeyViolation),
                ("UPDATE client_manager_group_assignments SET group_id='30000000-0000-0000-0000-000000000002' "
                 "WHERE id='f0000000-0000-0000-0000-000000000004'", psycopg2.errors.ForeignKeyViolation),
            )
            for statement, exception in attempts:
                try:
                    cursor.execute(statement)
                except exception:
                    cursor.execute("ROLLBACK TO SAVEPOINT detached_manager")
                else:
                    raise AssertionError("Detached manager constraint failed to reject unsafe authority")
    finally:
        connection.rollback()
