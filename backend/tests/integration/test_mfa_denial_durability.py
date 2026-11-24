"""MFA denials persist through the real request commit/rollback dependency."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.security.identity_security import totp_code
from app.infrastructure.database.models import DashboardAuthChallengeModel, UserSecurityStateModel
from tests.integration.test_auth_response_durability import (
    SECRET,
    prepare_request,
)
from tests.integration.test_auth_response_durability import auth_database as auth_database


async def post(app, path, headers, body):
    payload = json.dumps(body).encode()
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
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    assert start["status"] == 401
    assert not any(name == b"set-cookie" for name, _ in start["headers"])


@pytest.mark.parametrize("flow", ["verify_mfa", "verify_enrollment"])
async def test_failed_factors_exhaust_durable_attempts_across_fresh_requests(auth_database, flow):
    env = auth_database
    path, headers, payload = await prepare_request(env.sessions, flow)
    body = json.loads(payload)
    body["code"] = "AAAA-BBBB-CCCC-DDDD"  # Never issued as a recovery code.
    env.gate.release.set()
    for attempt in range(1, 6):
        await post(env.app, path, headers, body)
        async with env.sessions() as reader:
            challenge = await reader.scalar(select(DashboardAuthChallengeModel))
            assert challenge.attempt_count == attempt
            assert challenge.status == ("locked" if attempt == 5 else "pending")
    body["code"] = totp_code(SECRET, counter=int(datetime.now(UTC).timestamp()) // 30)
    await post(env.app, path, headers, body)
    async with env.sessions() as reader:
        challenge = await reader.scalar(select(DashboardAuthChallengeModel))
        assert challenge.status == "locked" and challenge.attempt_count == 5


@pytest.mark.parametrize("reason", ["request_binding", "credential_state", "factor_unavailable"])
async def test_cancelled_challenge_stays_cancelled_after_http_failure(auth_database, reason):
    env = auth_database
    path, headers, payload = await prepare_request(env.sessions, "verify_mfa")
    if reason == "request_binding":
        headers = [*headers, (b"user-agent", b"different-client")]
    else:
        async with env.sessions() as session, session.begin():
            state = await session.scalar(select(UserSecurityStateModel))
            if reason == "credential_state":
                state.credential_state = "invited"
            else:
                state.mfa_secret_ciphertext = None
                state.mfa_enabled_at = None
    env.gate.release.set()
    await post(env.app, path, headers, json.loads(payload))
    async with env.sessions() as reader:
        challenge = await reader.scalar(select(DashboardAuthChallengeModel))
        assert challenge.status == "cancelled"
