"""GC App publication and contact/session boundaries against real PostgreSQL.

Uses the explicit isolated database and optional schema retention of the FCM
acceptance fixture. No provider is contacted and no production row is loaded.
"""

import asyncio
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.infrastructure.database.gc_mobile_models import GCAnnouncementModel, GCGroupAccessModel
from app.presentation.api.v1.routes.gc_app_content import create_announcement
from tests.gc_app_workflow_fixtures import workflow_group, workflow_passenger, workflow_session
from tests.service_integration.test_fcm_dispatch_postgresql import pg_factory as pg_factory
from tests.unit.application.test_passenger_session_authority import (
    test_changed_nonselected_contact_revokes_session_durably_without_deleting_data as test_changed_nonselected_contact_revokes_session_durably_without_deleting_data,
)
from tests.unit.application.test_passenger_session_authority import (
    test_unchanged_submitted_contacts_keep_existing_session_and_refresh_token as test_unchanged_submitted_contacts_keep_existing_session_and_refresh_token,
)
from tests.unit.presentation.test_gc_app_announcement_atomic_publish import (
    body,
    request,
)
from tests.unit.presentation.test_gc_app_announcement_atomic_publish import (
    test_failed_publication_rolls_back_draft_and_revision_so_safe_retry_creates_once as test_failed_publication_rolls_back_draft_and_revision_so_safe_retry_creates_once,
)
from tests.unit.presentation.test_gc_app_replacement_publish import (
    test_lower_uuid_replacement_retires_old_version_before_promotion as test_lower_uuid_replacement_retires_old_version_before_promotion,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


@pytest.fixture
async def db_session(pg_factory):
    async with pg_factory() as session:
        yield session


async def test_concurrent_operator_save_publish_accepts_only_one_revision(pg_factory):
    async with pg_factory() as session:
        actor, group, access = await workflow_group(session)
        group_id, revision = group.id, access.revision
        await session.commit()

    async def publish():
        async with pg_factory() as session:
            try:
                async with session.begin():
                    result = await create_announcement(group_id, body(revision), request(), None, actor, session)
                    return result.status
            except HTTPException as error:
                return error.status_code

    results = await asyncio.wait_for(asyncio.gather(publish(), publish()), timeout=20)
    assert set(results) == {"published", 409}
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 1
        current = (await session.scalars(select(GCGroupAccessModel))).one()
        assert current.revision == revision + 2 and current.announcement_version == 1


async def test_cached_submission_is_rechecked_after_another_transaction_changes_phone(pg_factory):
    from app.application.mobile.passenger_session_authority import (
        ensure_current_passenger_session_bindings,
    )
    from app.infrastructure.database.models import PassportSubmissionModel

    async with pg_factory() as reader:
        _, _, access = await workflow_group(reader)
        submission, identity = await workflow_passenger(reader, access)
        device, _ = await workflow_session(reader, [identity])
        submission_id = submission.id
        assert await ensure_current_passenger_session_bindings(reader, device)
        async with pg_factory() as writer:
            current = await writer.get(PassportSubmissionModel, submission_id)
            current.client_phone = "+919876543211"
            await writer.commit()
        assert not await ensure_current_passenger_session_bindings(reader, device)
        assert device.status == "revoked"
