"""Factor mutations publish durable effects and cannot renew a revoked request."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import verify_password
from app.infrastructure.database.models import DashboardSessionModel, UserSecurityStateModel
from app.presentation.middleware.error_handler import register_exception_handlers
from tests.integration.test_auth_response_durability import (
    NEW_PASSWORD,
    PASSWORD,
    prepare_request,
    snapshot,
)
from tests.integration.test_auth_response_durability import auth_database as auth_database
from tests.integration.test_mfa_denial_durability import post


@pytest.mark.parametrize("commit_fails", [False, True])
async def test_password_change_waits_for_commit_before_clearing_cookies(
    auth_database, commit_fails
):
    env = auth_database
    _, headers, _ = await prepare_request(env.sessions, "regenerate_codes")
    baseline = await snapshot(env.sessions)
    env.gate.fail = commit_fails
    path = "/api/v1/auth/password/change"
    payload = json.dumps({"current_password": PASSWORD, "new_password": NEW_PASSWORD}).encode()
    messages = []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": None,
        "server": ("testserver", 80),
    }
    task = asyncio.create_task(env.app(scope, receive, send))
    try:
        await asyncio.wait_for(env.gate.entered.wait(), 10)
        assert messages == [], "Password-change response escaped before its durable commit"
        assert await snapshot(env.sessions) == baseline
    finally:
        env.gate.release.set()
        if commit_fails:
            with pytest.raises(SQLAlchemyError, match="synthetic commit failure"):
                await asyncio.wait_for(task, 10)
        else:
            await asyncio.wait_for(task, 10)
    start = next(message for message in messages if message["type"] == "http.response.start")
    final = await snapshot(env.sessions)
    if commit_fails:
        assert start["status"] == 500
        assert not any(name == b"set-cookie" for name, _ in start["headers"])
        assert final == baseline
    else:
        assert start["status"] == 204
        assert verify_password(NEW_PASSWORD, final["users"][0][1])
        assert final["security"][0][1] == baseline["security"][0][1] + 1
        assert all(revoked for _, revoked in final["refresh"])
        assert all(revoked is not None for (revoked,) in final["families"])


@pytest.mark.parametrize("fence", ["generation", "family"])
@pytest.mark.parametrize("flow", ["regenerate_codes", "password_change"])
async def test_factor_mutation_rechecks_authority_after_account_wait(
    auth_database,
    monkeypatch,
    fence,
    flow,
):
    env = auth_database
    path, headers, payload = await prepare_request(env.sessions, "regenerate_codes")
    if flow == "password_change":
        path = "/api/v1/auth/password/change"
        payload = json.dumps({"current_password": PASSWORD, "new_password": NEW_PASSWORD}).encode()
    register_exception_handlers(env.app)
    baseline = await snapshot(env.sessions)
    env.gate.release.set()
    original_scalar = AsyncSession.scalar
    original_execute = AsyncSession.execute
    pending = True

    async def fence_before_lock(statement):
        nonlocal pending
        locked = getattr(statement, "_for_update_arg", None) is not None
        tables = (
            {getattr(table, "name", None) for table in statement.get_final_froms()}
            if locked and statement.is_select
            else set()
        )
        if pending and locked and "users" in tables:
            pending = False
            # Commit through an independent connection after the JWT dependency
            # succeeded, immediately before the handler's first account lock.
            async with env.sessions() as administrator:
                if fence == "generation":
                    await administrator.execute(
                        update(UserSecurityStateModel).values(
                            session_version=UserSecurityStateModel.session_version + 1,
                        )
                    )
                else:
                    await administrator.execute(
                        update(DashboardSessionModel).values(
                            revoked_at=datetime.now(UTC),
                            revocation_reason="synthetic_logout",
                        )
                    )
                await administrator.commit()

    async def fenced_scalar(session, statement, *args, **kwargs):
        await fence_before_lock(statement)
        return await original_scalar(session, statement, *args, **kwargs)

    async def fenced_execute(session, statement, *args, **kwargs):
        await fence_before_lock(statement)
        return await original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", fenced_scalar)
    monkeypatch.setattr(AsyncSession, "execute", fenced_execute)
    await post(env.app, path, headers, json.loads(payload))
    assert not pending
    final = await snapshot(env.sessions)
    assert final["recovery_codes"] == baseline["recovery_codes"]
    assert len(final["refresh"]) == len(baseline["refresh"])
    assert len(final["families"]) == len(baseline["families"])
    async with env.sessions() as reader:
        if fence == "generation":
            state = await reader.scalar(select(UserSecurityStateModel))
            assert state.session_version == baseline["security"][0][1] + 1
        else:
            family = await reader.scalar(select(DashboardSessionModel))
            assert family.revoked_at is not None
