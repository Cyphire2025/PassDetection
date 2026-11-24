"""Private assistant authority races in the isolated PostgreSQL service lane."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, func, select

from app.application.assistant.settings_contracts import (
    AssistantConfiguration,
    AssistantSettingsUpdate,
)
from app.application.mcp.assistant_authority import ensure_assistant_authority
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.permissions import require_tool_access
from app.infrastructure.assistant.settings_store import SETTINGS_KEY, load_snapshot, save_settings
from app.infrastructure.database.dashboard_session_models import DashboardSessionModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.models import AuditLogModel, PlatformSettingModel, UserModel
from app.infrastructure.repositories.user_repository import UserRepository
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.service_integration.test_mcp_concurrency_postgresql import seed_code

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


async def seed_assistant(fixture):
    sessions, settings = fixture
    _, external_id = await seed_code(fixture)
    async with sessions() as session:
        external = await session.get(MCPGrantModel, external_id)
        actor = await UserRepository(session).get_by_id(external.user_id)
        now, session_id = datetime.now(UTC), uuid.uuid4()
        session.add(DashboardSessionModel(id=session_id, user_id=actor.id, session_version=actor.session_version,
            expires_at=now + timedelta(hours=8)))
        before = await load_snapshot(session)
        await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=before.revision,
            configuration=AssistantConfiguration(mcp_write_enabled=True)))
        claims = {"sub": str(actor.id), "sv": actor.session_version, "sid": str(session_id),
                  "amr": ["totp"], "mfa_at": now.timestamp()}
        return actor, claims


async def test_first_party_authority_materializes_once_under_contention(mcp_sessions):
    sessions, settings = mcp_sessions
    actor, claims = await seed_assistant(mcp_sessions)

    async def create():
        async with sessions() as session:
            grant = await ensure_assistant_authority(session, settings, actor, claims)
            await session.commit()
            return grant.id

    ids = await asyncio.wait_for(asyncio.gather(*(create() for _ in range(6))), 15)
    assert set(ids) == {uuid.UUID(claims["sid"])}
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(MCPGrantModel)
            .where(MCPGrantModel.id == ids[0])) == 1
        assert await session.scalar(select(func.count()).select_from(AuditLogModel).where(
            AuditLogModel.action == "assistant.authority.created", AuditLogModel.entity_id == str(ids[0]))) == 1


async def test_ai_write_disable_fences_a_waiting_internal_worker(mcp_sessions):
    sessions, settings = mcp_sessions
    actor, claims = await seed_assistant(mcp_sessions)
    async with sessions() as session:
        grant = await ensure_assistant_authority(session, settings, actor, claims)
        grant_id = grant.id
        await session.commit()
    attempted = asyncio.Event()
    async with sessions() as writer, sessions() as worker:
        row = await writer.scalar(select(PlatformSettingModel).where(
            PlatformSettingModel.key == SETTINGS_KEY).with_for_update())

        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            if "platform_settings" in statement and "FOR SHARE" in statement:
                attempted.set()

        connection = await worker.connection()
        event.listen(connection.sync_connection, "before_cursor_execute", observe)

        async def run():
            await MCPAuthorizationService(worker, settings).require_grant(grant_id, lock=True)
            await require_tool_access(worker, settings, grant_id, "create_group", "mcp:change")

        pending = asyncio.create_task(run())
        try:
            await asyncio.wait_for(attempted.wait(), 5)
            assert not pending.done()
            value = dict(row.value)
            value["revision"] += 1
            value["configuration"] = dict(value["configuration"], mcp_write_enabled=False)
            row.value = value
            await writer.commit()
            with pytest.raises(MCPAuthError, match="write_access_denied"):
                await asyncio.wait_for(pending, 5)
            await worker.rollback()
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            event.remove(connection.sync_connection, "before_cursor_execute", observe)


async def test_dashboard_logout_fences_worker_without_identity_session_deadlock(mcp_sessions):
    sessions, settings = mcp_sessions
    actor, claims = await seed_assistant(mcp_sessions)
    async with sessions() as session:
        grant = await ensure_assistant_authority(session, settings, actor, claims)
        grant_id = grant.id
        await session.commit()
    attempted = asyncio.Event()
    async with sessions() as logout, sessions() as worker:
        await logout.scalar(select(UserModel).where(UserModel.id == actor.id).with_for_update())

        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            if "user_security_states" in statement and "FOR SHARE" in statement:
                attempted.set()

        connection = await worker.connection()
        event.listen(connection.sync_connection, "before_cursor_execute", observe)
        pending = asyncio.create_task(MCPAuthorizationService(worker, settings).require_grant(grant_id, lock=True))
        try:
            await asyncio.wait_for(attempted.wait(), 5)
            assert not pending.done()
            # Logout/refresh already own identity and next acquire the family.
            # A worker must not hold that family while waiting for identity.
            family = await asyncio.wait_for(logout.scalar(select(DashboardSessionModel).where(
                DashboardSessionModel.id == grant_id).with_for_update()), 5)
            family.revoked_at = datetime.now(UTC)
            await logout.commit()
            with pytest.raises(MCPAuthError):
                await asyncio.wait_for(pending, 5)
            await worker.rollback()
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            event.remove(connection.sync_connection, "before_cursor_execute", observe)
