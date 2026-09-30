"""Existing queued MCP plans cannot cross the new deployment ceiling.

The fixtures prepare real retained rows under broad authority first. All broker
and provider functions are synthetic; ordinary website batch authority remains
independent of the MCP deployment mode.
"""

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.whatsapp import mcp_publication
from app.infrastructure.whatsapp.mcp_dispatch import BLOCKED, authorize_mcp_batch_dispatch
from app.infrastructure.whatsapp.mcp_media_dispatch import ready_plan_media
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.integration.test_mcp_whatsapp_intents import confirm, prepare
from tests.integration.test_mcp_whatsapp_intents import intent_fixture as intent_fixture
from tests.integration.test_mcp_whatsapp_messages import confirm as confirm_media
from tests.integration.test_mcp_whatsapp_messages import message_fixture as message_fixture
from tests.integration.test_mcp_whatsapp_messages import prepare as prepare_media
from tests.unit.presentation.test_whatsapp_repeatable_reminders import broadcast as broadcast


async def test_read_only_deployment_retains_queued_reminder_without_publication_or_provider(intent_fixture):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    await confirm(fixture, prepared, connection=1)
    session, settings = fixture[0][0], fixture[2]
    await session.commit()
    plan = await session.scalar(select(MCPWhatsAppPlanModel))
    outbox = await session.scalar(select(MCPWhatsAppOutboxModel))
    logs = list(await session.scalars(select(WhatsAppMessageLogModel)))
    retained = (plan.status, plan.revision, outbox.status, outbox.publication_attempts,
                outbox.next_attempt_at, [(row.id, row.status) for row in logs])
    settings.mcp.read_only_mode = True
    assert await mcp_publication._reserve_publication(outbox.id) is None
    assert await authorize_mcp_batch_dispatch(session, log=logs[0], settings=settings) == BLOCKED
    await session.refresh(plan)
    await session.refresh(outbox)
    for row in logs:
        await session.refresh(row)
    assert (plan.status, plan.revision, outbox.status, outbox.publication_attempts,
            outbox.next_attempt_at, [(row.id, row.status) for row in logs]) == retained
    fixture[1].publication.assert_not_awaited()
    fixture[4].assert_not_awaited()


async def test_read_only_deployment_rejects_previously_owned_ready_header(message_fixture):
    fixture = message_fixture
    preview = await prepare_media(fixture, "passport_link")
    await confirm_media(fixture, preview, connection=1)
    await fixture.session.commit()
    plan = await fixture.session.get(MCPWhatsAppPlanModel, uuid.UUID(preview["data"]["plan_id"]))
    log = await fixture.session.scalar(select(WhatsAppMessageLogModel))
    original = fixture.grants[0]
    # Prove the retained native authority and exact header were valid before mode.
    assert await ready_plan_media(fixture.session, plan, original, fixture.settings)
    assert await authorize_mcp_batch_dispatch(fixture.session, log=log, settings=fixture.settings) is None
    retained = (plan.status, plan.revision, fixture.media.status, fixture.media.revision, log.status)
    fixture.settings.mcp.read_only_mode = True
    assert not await ready_plan_media(fixture.session, plan, original, fixture.settings)
    assert await authorize_mcp_batch_dispatch(fixture.session, log=log, settings=fixture.settings) == BLOCKED
    assert (plan.status, plan.revision, fixture.media.status, fixture.media.revision, log.status) == retained
    fixture.provider.assert_not_awaited()


async def test_read_only_mode_preserves_ordinary_website_batch_authority(intent_fixture):
    session, settings = intent_fixture[0][0], intent_fixture[2]
    settings.mcp.read_only_mode = True
    # No MCP outbox binding: the existing website worker's own policy applies.
    website_log = SimpleNamespace(batch_id=uuid.uuid4())
    assert await authorize_mcp_batch_dispatch(session, log=website_log, settings=settings) is None
    intent_fixture[4].assert_not_awaited()
