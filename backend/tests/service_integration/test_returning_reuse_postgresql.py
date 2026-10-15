"""Opt-in real PostgreSQL lock/idempotency races; never a SQLite substitute."""

import asyncio
import os

import pytest
from sqlalchemy import func, select

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.draft_completion import complete_draft
from app.application.travellers.errors import ReuseError
from app.application.travellers.grants import require_grant
from app.infrastructure.database.traveller_reuse_models import TravellerContactBindingModel
from tests.integration.test_returning_completion import completion_context
from tests.integration.test_returning_contact_change import NEW_PHONE, pending_change, verify_change
from tests.service_integration.test_fcm_dispatch_postgresql import pg_factory as pg_factory

pytestmark = [pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


async def test_parallel_contact_retries_create_one_binding_without_deadlock(pg_factory, test_settings):
    async with pg_factory() as session:
        service, _, _, person, token, _ = await completion_context(session, test_settings)
        pending, provider = await pending_change(service, token)
        secret, body = await verify_change(service, token, pending, provider.code)
        await session.commit()
        settings, person_id = service.reuse_settings, person.profile.id

    async def finish():
        async with pg_factory() as session:
            return await complete_draft(ReturningClaims(session, test_settings, settings), token, secret, body)

    results = await asyncio.wait_for(asyncio.gather(finish(), finish()), timeout=15)
    assert results[0] == results[1]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(TravellerContactBindingModel).where(
            TravellerContactBindingModel.traveller_id == person_id,
            TravellerContactBindingModel.status == "current")) == 1
        binding = await session.scalar(select(TravellerContactBindingModel).where(
            TravellerContactBindingModel.traveller_id == person_id,
            TravellerContactBindingModel.status == "current"))
        assert ReturningClaims(session, test_settings, settings).crypto.decrypt(binding.value_ciphertext) == NEW_PHONE


async def test_contact_recovery_and_old_grant_reads_share_lock_order(pg_factory, test_settings):
    async with pg_factory() as session:
        service, _, _, person, token, _ = await completion_context(session, test_settings)
        pending, provider = await pending_change(service, token)
        secret, body = await verify_change(service, token, pending, provider.code)
        await session.commit()
        settings = service.reuse_settings

    async def read():
        async with pg_factory() as session:
            try:
                await require_grant(ReturningClaims(session, test_settings, settings), token, "history:read")
                await session.commit()
                return "valid_before_recovery"
            except ReuseError:
                await session.rollback()
                return "revoked_after_recovery"

    async def finish():
        async with pg_factory() as session:
            return await complete_draft(ReturningClaims(session, test_settings, settings), token, secret, body)

    await asyncio.wait_for(asyncio.gather(read(), finish(), read()), timeout=15)
    assert await read() == "revoked_after_recovery"
