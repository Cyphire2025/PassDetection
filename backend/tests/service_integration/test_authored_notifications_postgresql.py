"""Canonical PostgreSQL transaction proof in the explicitly isolated test DB.

Uses the UUID-schema fixture and FCM_TEST_KEEP_SCHEMA retention contract. Every
provider is absent/fake, and no application database or existing schema is used.
"""

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.application.mobile.authored_notification_service import send_notification
from app.infrastructure.database.gc_mobile_models import MobileNotificationModel
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationRecipientModel,
)
from tests.authored_notification_fixtures import authored_audience, reviewed_draft
from tests.service_integration.test_fcm_dispatch_postgresql import pg_factory as pg_factory
from tests.unit.application.test_authored_notification_delivery import (
    test_rotated_registration_does_not_repeat_accepted_or_uncertain_physical_device_attempt as test_rotated_registration_does_not_repeat_accepted_or_uncertain_physical_device_attempt,
)
from tests.unit.application.test_authored_notifications import (
    test_all_original_grants_lost_cancels_without_adding_new_group as test_all_original_grants_lost_cancels_without_adding_new_group,
)
from tests.unit.application.test_authored_notifications import (
    test_all_three_roles_are_deduplicated_and_coordinator_local_expiry_is_immediate as test_all_three_roles_are_deduplicated_and_coordinator_local_expiry_is_immediate,
)
from tests.unit.application.test_authored_notifications import (
    test_audience_change_between_review_and_send_requires_fresh_review as test_audience_change_between_review_and_send_requires_fresh_review,
)
from tests.unit.application.test_authored_notifications import (
    test_completed_request_recovers_after_preview_expiry_and_later_draft_edit as test_completed_request_recovers_after_preview_expiry_and_later_draft_edit,
)
from tests.unit.application.test_authored_notifications import (
    test_deleted_trip_does_not_cascade_entire_other_trip_alert as test_deleted_trip_does_not_cascade_entire_other_trip_alert,
)
from tests.unit.application.test_authored_notifications import (
    test_explicit_batch_is_idempotent_and_new_request_is_deliberate_resend as test_explicit_batch_is_idempotent_and_new_request_is_deliberate_resend,
)
from tests.unit.application.test_authored_notifications import (
    test_one_revoked_trip_preserves_other_original_grant_and_device_union as test_one_revoked_trip_preserves_other_original_grant_and_device_union,
)
from tests.unit.application.test_authored_notifications import (
    test_separate_batches_for_same_phone_never_share_unrelated_trip_device_grants as test_separate_batches_for_same_phone_never_share_unrelated_trip_device_grants,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="explicit isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def db_session(pg_factory):
    async with pg_factory() as session:
        yield session


async def test_concurrent_same_request_creates_one_batch_and_one_notification_per_person(
    pg_factory,
):
    async with pg_factory() as session:
        actor, _, _, _, _ = await authored_audience(session, device=False)
        draft, _, request = await reviewed_draft(session, actor)
        draft_id = draft.id
        await session.commit()

    async def send():
        async with pg_factory() as session:
            async with session.begin():
                batch = await send_notification(
                    session,
                    agency_id=actor.agency_id,
                    actor_id=actor.id,
                    draft_id=draft_id,
                    body=request,
                )
                return batch.id

    ids = await asyncio.wait_for(asyncio.gather(send(), send()), timeout=20)
    assert ids[0] == ids[1]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(GCNotificationRecipientModel))
            == 2
        )
        assert await session.scalar(select(func.count()).select_from(MobileNotificationModel)) == 2


async def test_send_rollback_preserves_draft_and_same_request_can_retry(pg_factory):
    async with pg_factory() as session:
        actor, _, _, _, _ = await authored_audience(session, device=False)
        draft, _, request = await reviewed_draft(session, actor)
        draft_id = draft.id
        await session.commit()
        await send_notification(
            session, agency_id=actor.agency_id, actor_id=actor.id, draft_id=draft_id, body=request
        )
        await session.rollback()
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MobileNotificationModel)) == 0
        batch = await send_notification(
            session, agency_id=actor.agency_id, actor_id=actor.id, draft_id=draft_id, body=request
        )
        await session.commit()
        assert batch.request_id == request.request_id
        assert (
            await session.scalar(select(func.count()).select_from(GCNotificationRecipientModel))
            == 2
        )


async def test_same_request_id_different_drafts_conflicts_without_duplicate_batch(pg_factory):
    async with pg_factory() as session:
        actor, _, _, _, _ = await authored_audience(session, device=False)
        first, _, request = await reviewed_draft(session, actor)
        second, _, second_request = await reviewed_draft(session, actor)
        second_request.request_id = request.request_id
        first_id, second_id = first.id, second.id
        await session.commit()

    async def send(draft_id, body):
        async with pg_factory() as session:
            try:
                async with session.begin():
                    await send_notification(
                        session,
                        agency_id=actor.agency_id,
                        actor_id=actor.id,
                        draft_id=draft_id,
                        body=body,
                    )
                return "sent"
            except HTTPException as error:
                return error.detail

    results = await asyncio.wait_for(
        asyncio.gather(send(first_id, request), send(second_id, second_request)), timeout=20
    )
    assert set(results) == {"sent", "idempotency_conflict"}


async def test_additive_0097_preserves_legacy_rows_and_terminal_evidence(pg_factory):
    """Run the frozen migration against a fresh miniature0096 schema, not ORM0097."""
    schema = f"authored_migration_test_{uuid.uuid4().hex}"
    async with pg_factory() as session:
        original = await session.scalar(text("SELECT current_schema()"))
        await session.execute(text(f'CREATE SCHEMA "{schema}"'))
        await session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await session.execute(text("CREATE TABLE agencies (id uuid PRIMARY KEY)"))
        await session.execute(text("CREATE TABLE users (id uuid PRIMARY KEY)"))
        await session.execute(text("CREATE TABLE mobile_push_registrations (id uuid PRIMARY KEY)"))
        await session.execute(
            text("""CREATE TABLE mobile_notifications (
            id uuid PRIMARY KEY, agency_id uuid, group_id uuid, gc_group_access_id uuid,
            recipient_type varchar(24), recipient_passenger_identity_id uuid, recipient_user_id uuid,
            notification_type varchar(64), status varchar(16), available_at timestamptz,
            CONSTRAINT ck_mobile_notification_recipient_type CHECK(recipient_type IN ('passenger','client_manager','coordinator')),
            CONSTRAINT ck_mobile_notification_recipient_shape CHECK(recipient_type != 'passenger' OR recipient_passenger_identity_id IS NOT NULL))""")
        )
        await session.execute(
            text(
                "CREATE TABLE mobile_push_deliveries (id uuid PRIMARY KEY, notification_id uuid, status varchar(24), provider_ticket_id varchar(255), last_error_code varchar(80), updated_at timestamptz)"
            )
        )
        agency, notification_id = uuid.uuid4(), uuid.uuid4()
        await session.execute(text("INSERT INTO agencies VALUES(:id)"), {"id": agency})
        await session.execute(
            text(
                "INSERT INTO mobile_notifications(id, agency_id, recipient_type, recipient_user_id, notification_type, status) VALUES(:id,:agency,'coordinator',:user,'group_announcement','queued')"
            ),
            {"id": notification_id, "agency": agency, "user": uuid.uuid4()},
        )
        for state, ticket in (
            ("retry", None),
            ("submitting", None),
            ("provider_accepted", "accepted-ticket"),
        ):
            await session.execute(
                text(
                    "INSERT INTO mobile_push_deliveries VALUES(:id,:notification,:state,:ticket,NULL,CURRENT_TIMESTAMP)"
                ),
                {
                    "id": uuid.uuid4(),
                    "notification": notification_id,
                    "state": state,
                    "ticket": ticket,
                },
            )
        path = (
            Path(__file__).resolve().parents[2] / "alembic/versions/0097_authored_notifications.py"
        )
        spec = importlib.util.spec_from_file_location("authored_0097_test", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        connection = await session.connection()

        def apply(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration.upgrade()

        await connection.run_sync(apply)
        states = dict(
            (
                await session.execute(
                    text("SELECT status,last_error_code FROM mobile_push_deliveries")
                )
            ).all()
        )
        assert states == {
            "cancelled": "announcement_in_app_only",
            "unknown": "provider_outcome_unknown",
            "provider_accepted": None,
        }
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM mobile_notifications WHERE notification_type='group_announcement' AND status='queued'"
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND table_name='mobile_push_registrations' AND column_name='apns_environment'"
                ),
                {"schema": schema},
            )
            == 1
        )
        await session.commit()
        print(f"AUTHORED_MIGRATION_SCHEMA_RETAINED={schema}; ORIGINAL_SCHEMA={original}")
