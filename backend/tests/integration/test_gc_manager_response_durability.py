"""One-time manager activation links cannot escape before their durable commit."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.security.jwt import create_access_token, decode_access_token
from app.core.security.mobile_jwt import hash_mobile_lookup
from app.core.security.password import hash_password
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    ClientOrganizationModel,
)
from app.infrastructure.database.models import AgencyModel, AuditLogModel, UserModel
from app.presentation.api.v1.routes.gc_app import router
from app.presentation.middleware.error_handler import register_exception_handlers
from tests.integration.test_auth_response_durability import PASSWORD, prepare_request
from tests.integration.test_auth_response_durability import auth_database as auth_database

BASE = "/api/v1/gc-app/admin"


async def prepare_manager_command(env, flow):
    _, initial_headers, _ = await prepare_request(env.sessions, "regenerate_codes")
    original = decode_access_token(
        next(value.decode()[7:] for name, value in initial_headers if name == b"authorization")
    )
    actor_id = uuid.UUID(original["sub"])
    now = datetime.now(UTC)
    agency_id, organization_id = uuid.uuid4(), uuid.uuid4()
    async with env.sessions() as session, session.begin():
        session.add(
            AgencyModel(id=agency_id, name="Synthetic Agency", email="gc-agency@example.test")
        )
        await session.flush()
        actor = await session.get(UserModel, actor_id)
        actor.role, actor.agency_id = "agency_admin", agency_id
        session.add(
            ClientOrganizationModel(
                id=organization_id,
                agency_id=agency_id,
                name="Synthetic Company",
                normalized_name="synthetic company",
                status="active",
                created_by_user_id=actor_id,
            )
        )
        await session.flush()
        path = f"{BASE}/client-managers"
        body = {
            "full_name": "Synthetic Manager",
            "email": "gc-manager@example.com",
            "phone_number": "+919999000001",
            "organization_id": str(organization_id),
        }
        if flow == "reinvite":
            manager_id, profile_id = uuid.uuid4(), uuid.uuid4()
            session.add(
                UserModel(
                    id=manager_id,
                    role="client_manager",
                    agency_id=agency_id,
                    email="gc-manager@example.com",
                    full_name="Synthetic Manager",
                    hashed_password=hash_password(PASSWORD),
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                ClientManagerProfileModel(
                    id=profile_id,
                    agency_id=agency_id,
                    user_id=manager_id,
                    organization_id=organization_id,
                    normalized_phone_number="+919999000001",
                    status="active",
                    activated_at=now,
                    access_generation=1,
                    revision=1,
                )
            )
            path, body = f"{BASE}/client-managers/{profile_id}/reset-password", {}
    token, _ = create_access_token(
        actor_id,
        "agency_admin",
        agency_id,
        session_version=original["sv"],
        session_id=uuid.UUID(original["sid"]),
        authentication_methods=("pwd", "totp"),
        mfa_authenticated_at=now,
        session_expires_at=datetime.fromtimestamp(original["session_exp"], UTC),
    )
    return (
        path,
        [(b"authorization", f"Bearer {token}".encode()), (b"content-type", b"application/json")],
        json.dumps(body).encode(),
    )


async def manager_snapshot(sessions):
    async with sessions() as session:
        profiles = list(
            (
                await session.execute(
                    select(
                        ClientManagerProfileModel.id,
                        ClientManagerProfileModel.status,
                        ClientManagerProfileModel.invitation_token_hash,
                        ClientManagerProfileModel.access_generation,
                        ClientManagerProfileModel.revision,
                        UserModel.hashed_password,
                    ).join(UserModel, UserModel.id == ClientManagerProfileModel.user_id)
                )
            ).all()
        )
        audits = list((await session.scalars(select(AuditLogModel.action))).all())
        return {"profiles": profiles, "audits": audits}


@pytest.mark.parametrize("flow", ["create", "reinvite"])
@pytest.mark.parametrize("commit_fails", [False, True])
async def test_manager_activation_response_waits_for_commit(auth_database, flow, commit_fails):
    env = auth_database
    env.app.include_router(router, prefix=BASE)
    register_exception_handlers(env.app)
    path, headers, payload = await prepare_manager_command(env, flow)
    before = await manager_snapshot(env.sessions)
    env.gate.fail = commit_fails
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
        assert not messages, "One-time manager credential escaped before its commit"
        assert await manager_snapshot(env.sessions) == before
    finally:
        env.gate.release.set()
        if commit_fails:
            with pytest.raises(SQLAlchemyError, match="synthetic commit failure"):
                await asyncio.wait_for(task, 10)
        else:
            await asyncio.wait_for(task, 10)
    start = next(message for message in messages if message["type"] == "http.response.start")
    after = await manager_snapshot(env.sessions)
    if commit_fails:
        assert start["status"] == 500
        assert after == before
        body = b"".join(message.get("body", b"") for message in messages)
        assert b"activation_token" not in body
    else:
        assert start["status"] == (201 if flow == "create" else 200)
        response = json.loads(b"".join(message.get("body", b"") for message in messages))
        assert len(after["profiles"]) == 1
        profile = after["profiles"][0]
        assert profile[1] == "invited"
        assert profile[2] == hash_mobile_lookup(
            response["activation_token"], purpose="manager-invitation"
        )
        action = (
            "gc_app.client_manager_created"
            if flow == "create"
            else "gc_app.client_manager_reinvited"
        )
        assert action in after["audits"]
