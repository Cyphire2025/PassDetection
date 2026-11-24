"""PostgreSQL synthetic rehearsal fixture owner."""

from __future__ import annotations

from psycopg2.extensions import connection as Connection

from scripts.postgresql_rehearsal_contract import IDS


def _seed_previous_release(connection: Connection) -> None:
    """Populate 0085 with synthetic cross-domain records and legacy backfill inputs."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO agencies (id, name, email, created_at, updated_at)
            VALUES
                (%(agency_a)s, 'CI Rehearsal Agency A', 'agency-a@example.invalid', now(), now()),
                (%(agency_b)s, 'CI Rehearsal Agency B', 'agency-b@example.invalid', now(), now());

            INSERT INTO users (
                id, email, hashed_password, full_name, role, agency_id, created_at, updated_at
            )
            VALUES
                (%(admin_a)s, 'admin-a@example.invalid', 'synthetic-not-a-password-hash',
                 'CI Admin A', 'agency_admin', %(agency_a)s, now(), now()),
                (%(coordinator_a)s, 'coordinator-a@example.invalid',
                 'synthetic-not-a-password-hash', 'CI Coordinator A',
                 'agency_coordinator', %(agency_a)s, now(), now()),
                (%(coordinator_b)s, 'coordinator-b@example.invalid',
                 'synthetic-not-a-password-hash', 'CI Coordinator B',
                 'agency_coordinator', %(agency_b)s, now(), now());

            INSERT INTO user_security_states (
                user_id, credential_state, session_version, password_changed_at,
                mfa_required, created_at, updated_at
            )
            VALUES
                (%(admin_a)s, 'active', 2, now(), true, now(), now()),
                (%(coordinator_a)s, 'active', 1, now(), false, now(), now()),
                (%(coordinator_b)s, 'active', 1, now(), false, now(), now());

            INSERT INTO platform_settings (key, value, updated_at)
            VALUES (
                'global',
                '{"passport_data_retention_days": 730, "synthetic_rehearsal": true}'::jsonb,
                now()
            );

            INSERT INTO client_groups (
                id, name, token, agency_id, status, created_by_user_id, created_at,
                closed_at, departure_cities, passport_purge_at,
                passport_retention_days_applied
            )
            VALUES
                (%(group_a)s, 'CI Closed Group A', 'ci-rehearsal-group-a', %(agency_a)s,
                 'closed', %(admin_a)s, now() - interval '40 days', now() - interval '10 days',
                 '["Delhi", "Mumbai"]'::jsonb, now() + interval '720 days', 730),
                (%(group_b)s, 'CI Active Group B', 'ci-rehearsal-group-b', %(agency_b)s,
                 'active', %(coordinator_b)s, now() - interval '5 days', NULL,
                 '[]'::jsonb, NULL, NULL);

            INSERT INTO passport_submissions (
                id, group_id, agency_id, client_name, client_email, image_s3_key,
                status, confirmed_fields, created_at, updated_at, confirmed_at
            )
            VALUES (
                %(passenger_a)s, %(group_a)s, %(agency_a)s, 'Synthetic Passenger',
                'passenger@example.invalid', 'ci-only/passports/synthetic.jpg', 'confirmed',
                '{"passport_number": "CI0000001", "synthetic": true}'::jsonb,
                now() - interval '9 days', now() - interval '8 days', now() - interval '8 days'
            );

            INSERT INTO attendance_sessions (
                id, agency_id, group_id, name, normalized_name, canonical_session_id,
                status, created_by_user_id, created_at, updated_at, started_at
            )
            VALUES (
                %(session_a)s, %(agency_a)s, %(group_a)s, 'Airport departure',
                'airport departure', %(session_a)s, 'active', %(coordinator_a)s,
                now() - interval '2 hours', now() - interval '1 hour',
                now() - interval '1 hour'
            );

            INSERT INTO attendance_records (
                id, agency_id, session_id, passenger_id, coordinator_user_id,
                scanned_at, sync_source, client_event_id, device_id, created_at
            )
            VALUES (
                %(attendance_a)s, %(agency_a)s, %(session_a)s, %(passenger_a)s,
                %(coordinator_a)s, now() - interval '30 minutes', 'offline',
                'ci-rehearsal-event-1', 'synthetic-device', now() - interval '29 minutes'
            );

            INSERT INTO attendance_closeout_checkpoints (
                id, session_id, coordinator_user_id, pending_count, sending_count,
                retryable_count, needs_review_count, unreviewed_rejected_count,
                oldest_pending_age_seconds, reported_at
            )
            VALUES (
                %(closeout_a)s, %(session_a)s, %(coordinator_a)s, 2, 1, 1, 1, 0, 90, now()
            );

            INSERT INTO rooming_hotels (
                id, agency_id, group_id, hotel_name, city, created_by_user_id,
                created_at, updated_at, allocation_updated_at
            )
            VALUES (
                %(hotel_a)s, %(agency_a)s, %(group_a)s, 'CI Rehearsal Hotel', 'Delhi',
                %(admin_a)s, now() - interval '7 days', now() - interval '6 days',
                now() - interval '5 days'
            );

            INSERT INTO gc_group_access (
                id, agency_id, group_id, is_enabled, passenger_access_enabled,
                coordinator_access_enabled, created_by_user_id, updated_by_user_id
            )
            VALUES
                (%(gc_access_a)s, %(agency_a)s, %(group_a)s, true, true, true,
                 %(admin_a)s, %(admin_a)s),
                (%(gc_access_b)s, %(agency_b)s, %(group_b)s, true, false, true,
                 %(coordinator_b)s, %(coordinator_b)s);

            INSERT INTO audit_logs (
                id, agency_id, user_id, actor_email, action, entity_type,
                entity_id, metadata, created_at
            )
            VALUES (
                %(audit_a)s, %(agency_a)s, %(admin_a)s, 'admin-a@example.invalid',
                'ci.rehearsal.seeded', 'client_group', %(group_a)s::text,
                '{"synthetic": true, "purpose": "restore-upgrade-rehearsal"}'::jsonb, now()
            );

            INSERT INTO identity_action_tokens (
                id, user_id, purpose, token_hash, expires_at, created_by_user_id,
                request_ip_hash, created_at
            )
            VALUES (
                %(identity_token_a)s, %(coordinator_a)s, 'activation',
                repeat('a', 64), now() + interval '1 day', %(admin_a)s,
                repeat('b', 64), now()
            );
            """,
            IDS,
        )
    connection.commit()


# Preserve canonical public import/pickle identities through the CLI facade.
for _export in (_seed_previous_release,):
    _export.__module__ = "scripts.rehearse_postgresql_upgrade"
del _export
