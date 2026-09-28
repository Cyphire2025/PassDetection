"""Authentication responses must follow their database commit, including failures.

HTTPX's ASGITransport waits for dependency cleanup, hiding the network-visible
response/commit race. Observe actual ASGI sends while the real session dependency
is blocked in commit, and read through an independent SQLite connection.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security.identity_security import (
    encrypt_mfa_secret,
    generate_recovery_codes,
    hash_recovery_code,
    totp_code,
)
from app.core.security.jwt import create_access_token
from app.core.security.password import hash_password, verify_password
from app.infrastructure.database import session as session_module
from app.infrastructure.database.models import (
    AuditLogModel,
    Base,
    DashboardAuthChallengeModel,
    DashboardSessionModel,
    IdentityActionTokenModel,
    MFARecoveryCodeModel,
    RefreshTokenModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.security.login_attempt_limiter import LoginAttemptLimiter
from app.presentation.api.v1.routes.auth import router

SECRET = "JBSWY3DPEHPK3PXP"
PASSWORD = "StrongPassword9"
NEW_PASSWORD = "ChangedStrongPassword8"
FLOWS = (
    "login_challenge", "login_enrollment", "login_password", "verify_mfa",
    "verify_enrollment", "refresh", "refresh_reuse",
    "activate_challenge", "activate_enrollment", "activate_coordinator",
    "recover_challenge", "recover_enrollment", "recover_coordinator", "regenerate_codes",
)


@pytest.fixture
async def auth_database(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    gate = SimpleNamespace(entered=asyncio.Event(), release=asyncio.Event(), fail=False)

    class GatedSession(AsyncSession):
        async def commit(self):
            gate.entered.set()
            await gate.release.wait()
            if gate.fail:
                raise SQLAlchemyError("synthetic commit failure")
            await super().commit()

    # Keep the actual get_db_session yield/commit/rollback lifecycle.
    monkeypatch.setattr(session_module, "AsyncSessionFactory",
                        async_sessionmaker(engine, class_=GatedSession, expire_on_commit=False))

    async def allow_attempt(*_args, **_kwargs):
        pass

    for method in ("check_allowed", "record_success", "record_failure"):
        monkeypatch.setattr(LoginAttemptLimiter, method, allow_attempt)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/auth")
    try:
        yield SimpleNamespace(app=app, sessions=sessions, gate=gate)
    finally:
        gate.release.set()
        await engine.dispose()


async def prepare_request(sessions, flow):
    now = datetime.now(UTC)
    enrollment = flow.endswith("enrollment")
    identity_action = flow.startswith(("activate_", "recover_"))
    headers = []
    async with sessions() as session:
        user = UserModel(email="durable@example.test", hashed_password=hash_password(PASSWORD),
                         full_name="Durability fixture", is_active=True,
                         role="agency_coordinator" if flow == "login_password" or flow.endswith("coordinator") else "agency_staff")
        session.add(user)
        await session.flush()
        session.add(UserSecurityStateModel(
            user_id=user.id, credential_state="invited" if flow.startswith("activate_") else "active", session_version=1,
            mfa_required=flow != "login_password",
            mfa_secret_ciphertext=None if enrollment else encrypt_mfa_secret(SECRET),
            mfa_enabled_at=None if enrollment else now,
        ))
        await session.flush()
        path = "/api/v1/auth/login"
        content_type = b"application/x-www-form-urlencoded"
        payload = urlencode({"username": user.email, "password": PASSWORD}).encode()
        if flow.startswith("verify_"):
            _, token = await IdentitySecurityRepository(session).issue_auth_challenge(
                user_id=user.id, purpose="mfa_enrollment" if enrollment else "mfa_login",
                pending_secret_ciphertext=encrypt_mfa_secret(SECRET) if enrollment else None,
                request_ip_hash=None, user_agent_hash=None,
            )
            path, content_type = "/api/v1/auth/mfa/verify", b"application/json"
            payload = json.dumps({"challenge_token": token,
                                  "code": totp_code(SECRET, counter=int(now.timestamp()) // 30)}).encode()
        elif flow.startswith("refresh"):
            repository = RefreshTokenRepository(session)
            first = await repository.save("original-refresh", user.id, now + timedelta(days=1),
                                          authentication_methods=("pwd", "totp"), mfa_authenticated_at=now)
            if flow == "refresh_reuse":
                await repository.claim_for_rotation("original-refresh")
                await repository.save("successor-refresh", user.id, first.expires_at,
                                      session_id=first.session_id,
                                      authentication_methods=("pwd", "totp"), mfa_authenticated_at=now)
            path, content_type = "/api/v1/auth/refresh", b"application/json"
            payload = json.dumps({"refresh_token": "original-refresh"}).encode()
        elif identity_action or flow == "regenerate_codes":
            # Existing sessions must be revoked atomically with changed factors.
            first = await RefreshTokenRepository(session).save(
                "original-refresh", user.id, now + timedelta(days=1),
                authentication_methods=("pwd", "totp"), mfa_authenticated_at=now,
            )
            repository = IdentitySecurityRepository(session)
            content_type = b"application/json"
            if identity_action:
                purpose = "activation" if flow.startswith("activate_") else "password_recovery"
                _, token = await repository.issue_action_token(
                    user_id=user.id, purpose=purpose, expires_in=timedelta(minutes=5),
                )
                path = "/api/v1/auth/activate" if purpose == "activation" else "/api/v1/auth/password/recovery/complete"
                payload = json.dumps({"token": token, "new_password": NEW_PASSWORD}).encode()
            else:
                await repository.replace_recovery_codes(
                    user_id=user.id, raw_codes=generate_recovery_codes(), now=now,
                )
                access, _ = create_access_token(
                    user.id, user.role, user.agency_id, session_id=first.session_id,
                    authentication_methods=("pwd", "totp"), mfa_authenticated_at=now,
                    session_expires_at=first.expires_at,
                )
                headers.append((b"authorization", f"Bearer {access}".encode()))
                path, payload = "/api/v1/auth/mfa/recovery-codes/regenerate", b"{}"
        await session.commit()
    return path, [(b"content-type", content_type), *headers], payload


async def snapshot(sessions):
    async with sessions() as session:
        return {
            "challenges": list((await session.execute(select(
                DashboardAuthChallengeModel.status,
            ))).all()),
            "security": list((await session.execute(select(
                UserSecurityStateModel.mfa_last_counter, UserSecurityStateModel.session_version,
                UserSecurityStateModel.mfa_enabled_at,
                UserSecurityStateModel.credential_state,
            ))).all()),
            "users": list((await session.execute(select(
                UserModel.id, UserModel.hashed_password, UserModel.last_login_at,
            ))).all()),
            "actions": list((await session.execute(select(
                IdentityActionTokenModel.consumed_at, IdentityActionTokenModel.invalidated_at,
            ))).all()),
            "recovery_codes": list((await session.execute(select(
                MFARecoveryCodeModel.code_hash,
            ).order_by(MFARecoveryCodeModel.code_hash))).scalars()),
            "families": list((await session.execute(select(
                DashboardSessionModel.revoked_at,
            ))).all()),
            "refresh": list((await session.execute(select(
                RefreshTokenModel.token, RefreshTokenModel.is_revoked,
            ).order_by(RefreshTokenModel.token))).all()),
            "audits": list((await session.execute(select(AuditLogModel.action))).scalars()),
        }


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("commit_fails", (False, True), ids=("commit", "rollback"))
async def test_auth_response_waits_for_durable_state(auth_database, flow, commit_fails):
    env = auth_database
    path, headers, payload = await prepare_request(env.sessions, flow)
    baseline = await snapshot(env.sessions)
    env.gate.fail = commit_fails
    messages = []
    at_response_start = []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.start":
            at_response_start.append(await snapshot(env.sessions))

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": path,
             "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": headers, "client": None,
             "server": ("testserver", 80)}
    task = asyncio.create_task(env.app(scope, receive, send))
    try:
        await asyncio.wait_for(env.gate.entered.wait(), 10)
        # No challenge, cookies, or status may escape while commit is pending.
        assert messages == [], "HTTP response escaped before the authentication commit"
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
    assert at_response_start == [final], "Auth state changed only after the response began"
    if commit_fails:
        assert start["status"] == 500
        assert not any(name == b"set-cookie" for name, _ in start["headers"])
        assert final == baseline, "Failed commit must roll back factors, sessions, and audits together"
        return
    assert start["status"] == (401 if flow == "refresh_reuse" else 200)
    body = json.loads(b"".join(message.get("body", b"") for message in messages))
    if flow.startswith(("activate_", "recover_")):
        assert final["actions"][0][0] is not None
        assert final["security"][0][1:] == (2, baseline["security"][0][2], "active")
        assert verify_password(NEW_PASSWORD, final["users"][0][1])
        assert all(revoked for _, revoked in final["refresh"])
        assert all(revoked_at is not None for (revoked_at,) in final["families"])
        expected_audit = "auth.account_activated" if flow.startswith("activate_") else "auth.password_recovered"
        assert expected_audit in final["audits"]
        if flow.endswith("coordinator"):
            assert body["status"] == "action_completed"
            assert body["next_step"] == "return_to_mobile_app"
            assert final["challenges"] == []
            return
    if "challenge_token" in body:
        async with env.sessions() as reader:
            assert await IdentitySecurityRepository(reader).get_pending_auth_challenge(
                raw_token=body["challenge_token"],
            ) is not None
        assert "auth.mfa_challenge_issued" in final["audits"]
    elif flow == "refresh_reuse":
        assert final["families"][0][0] is not None
        assert all(revoked for _, revoked in final["refresh"])
        assert "auth.refresh_reuse_detected" in final["audits"]
    else:
        cookies = SimpleCookie()
        for name, value in start["headers"]:
            if name == b"set-cookie":
                cookies.load(value.decode())
        async with env.sessions() as reader:
            refresh = await RefreshTokenRepository(reader).get_valid_token(cookies["refresh_token"].value)
            assert refresh is not None
            assert await reader.get(DashboardSessionModel, refresh.session_id) is not None
        if flow.startswith("verify_"):
            assert final["challenges"] == [("consumed",)]
            assert final["security"][0][0] is not None
            assert ("auth.mfa_enrolled" if flow == "verify_enrollment" else "auth.mfa_verified") in final["audits"]
        elif flow == "regenerate_codes":
            assert final["security"][0][1] == 2
            assert sum(revoked for _, revoked in final["refresh"]) == 1
            assert sum(revoked_at is not None for (revoked_at,) in final["families"]) == 1
            assert "auth.mfa_recovery_codes_regenerated" in final["audits"]
            assert len(body["recovery_codes"]) == 10
            assert final["recovery_codes"] == sorted(
                hash_recovery_code(code, user_id=final["users"][0][0])
                for code in body["recovery_codes"]
            )
            assert not set(final["recovery_codes"]) & set(baseline["recovery_codes"])
