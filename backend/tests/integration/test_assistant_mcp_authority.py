"""First-party session authority without external OAuth or device permissions."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.assistant.settings_contracts import (
    AssistantConfiguration,
    AssistantSettingsUpdate,
)
from app.application.mcp.assistant_authority import (
    ASSISTANT_CLIENT_ID,
    ensure_assistant_authority,
    validate_assistant_authority,
    validate_assistant_claims,
)
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.operations import MCPDatabaseOperation, MCPOperationService
from app.application.mcp.permissions import require_tool_access
from app.domain.entities.entities import UserRole
from app.infrastructure.assistant.settings_store import save_settings
from app.infrastructure.database.dashboard_session_models import DashboardSessionModel
from app.infrastructure.database.mcp_models import (
    MCPAuthorizationCodeModel,
    MCPControlModel,
    MCPGrantModel,
    MCPTokenModel,
)
from app.infrastructure.database.models import AgencyModel, UserSecurityStateModel
from app.infrastructure.repositories.user_repository import UserRepository
from tests.integration.test_mcp_operations import POLICY, create_agency
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def assistant_authority(operations_fixture):
    session, settings, model, external, tokens = operations_fixture
    actor = await UserRepository(session).get_by_id(model.id)
    now = datetime.now(UTC)
    dashboard = DashboardSessionModel(id=uuid.uuid4(), user_id=actor.id,
        session_version=actor.session_version, created_at=now, expires_at=now + timedelta(hours=8))
    session.add(dashboard)
    config = AssistantConfiguration()
    await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=0, configuration=config))
    claims = {"sub": str(actor.id), "sv": actor.session_version, "sid": str(dashboard.id),
              "amr": ["pwd", "totp"], "mfa_at": (now - timedelta(hours=2)).timestamp()}
    await session.commit()
    return session, settings, actor, claims, dashboard, external, tokens


async def private_token(session, settings, grant):
    raw = "gcmcp_access_" + uuid.uuid4().hex
    session.add(MCPTokenModel(token_hash=MCPAuthorizationService(session, settings).digest(raw),
        grant_id=grant.id, kind="access", expires_at=datetime.now(UTC) + timedelta(seconds=90)))
    await session.flush()
    return raw


async def configure(session, actor, revision, **values):
    await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=revision,
        configuration=AssistantConfiguration(**values)))
    await session.commit()


async def test_discovery_is_read_only_and_internal_authority_is_session_bound(assistant_authority):
    session, settings, actor, claims, dashboard, external, _ = assistant_authority
    control = await session.get(MCPControlModel, 1)
    policy = (control.enabled, control.write_enabled, list(control.allowed_write_tools))
    for grant in external:
        grant.revoked_at = datetime.now(UTC)
    await session.commit()
    assert await validate_assistant_authority(session, settings, actor, claims) is dashboard
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 2
    grant = await ensure_assistant_authority(session, settings, actor, claims)
    await session.commit()
    assert grant.id == dashboard.id and grant.client_id == ASSISTANT_CLIENT_ID
    assert utc(grant.expires_at) == utc(dashboard.expires_at)
    assert utc(grant.mfa_at).timestamp() == claims["mfa_at"]
    assert await ensure_assistant_authority(session, settings, actor, claims) is grant
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 3
    assert await session.scalar(select(func.count()).select_from(MCPAuthorizationCodeModel)) == 0
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == 2
    assert policy == (control.enabled, control.write_enabled, list(control.allowed_write_tools))
    assert all(item.revoked_at is not None for item in external)


@pytest.mark.parametrize("values", [
    {}, {"sub": str(uuid.uuid4())}, {"sv": 2}, {"sv": True}, {"sid": "invalid"},
    {"amr": ["pwd"]}, {"amr": "totp"}, {"amr": [{}]}, {"mfa_at": None},
    {"mfa_at": True}, {"mfa_at": float("nan")}, {"mfa_at": float("inf")},
    {"mfa_at": 10**1000}, {"mfa_at": -1},
    {"mfa_at": (datetime.now(UTC) + timedelta(hours=1)).timestamp()},
])
async def test_only_verified_session_and_real_mfa_claims_are_accepted(assistant_authority, values):
    session, settings, actor, claims, *_ = assistant_authority
    invalid = claims | values if values else {}
    with pytest.raises(MCPAuthError):
        await ensure_assistant_authority(session, settings, actor, invalid)
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 2


async def test_old_verified_mfa_is_not_fabricated_or_renewed(assistant_authority):
    session, settings, actor, claims, *_ = assistant_authority
    verified = validate_assistant_claims(actor, claims)
    assert datetime.now(UTC) - verified > timedelta(hours=1)
    grant = await ensure_assistant_authority(session, settings, actor, claims)
    assert utc(grant.mfa_at) == verified
    newer = claims | {"mfa_at": datetime.now(UTC).timestamp()}
    assert utc((await ensure_assistant_authority(session, settings, actor, newer)).mfa_at).timestamp() == newer["mfa_at"]


@pytest.mark.parametrize("restriction", ["session_revoked", "session_expired", "security_epoch", "mfa_removed", "grant_revoked", "grant_disabled", "grant_expired", "ai_disabled", "effective_role"])
async def test_live_revocation_denies_discovery_and_invocation(assistant_authority, restriction):
    session, settings, actor, claims, dashboard, *_ = assistant_authority
    grant = await ensure_assistant_authority(session, settings, actor, claims)
    await session.commit()
    if restriction == "session_revoked":
        dashboard.revoked_at = datetime.now(UTC)
    elif restriction == "session_expired":
        dashboard.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif restriction in {"security_epoch", "mfa_removed"}:
        security = await session.get(UserSecurityStateModel, actor.id)
        if restriction == "security_epoch":
            security.session_version += 1
        else:
            security.mfa_enabled_at = None
            security.mfa_secret_ciphertext = None
    elif restriction == "grant_revoked":
        grant.revoked_at = datetime.now(UTC)
    elif restriction == "grant_disabled":
        grant.enabled = False
    elif restriction == "grant_expired":
        grant.created_at = datetime.now(UTC) - timedelta(days=1)
        grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif restriction == "ai_disabled":
        await configure(session, actor, 1, enabled=False)
    else:
        actor = replace(actor, role=UserRole.AGENCY_ADMIN, actual_role=UserRole.SUPER_ADMIN)
    await session.commit()
    for check in (validate_assistant_authority, ensure_assistant_authority):
        with pytest.raises(MCPAuthError):
            await check(session, settings, actor, claims)
    if restriction != "effective_role":
        with pytest.raises(MCPAuthError):
            await MCPAuthorizationService(session, settings).require_grant(grant.id)
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 3


async def test_ai_write_gate_is_rechecked_in_existing_operations_and_replays(assistant_authority):
    session, settings, actor, claims, *_ = assistant_authority
    grant = await ensure_assistant_authority(session, settings, actor, claims)
    token = await private_token(session, settings, grant)
    operation = MCPOperationService(session, settings, [MCPDatabaseOperation(POLICY, create_agency)])
    arguments = {"access_token": token, "operation_name": POLICY.name,
                 "idempotency_key": "assistant-session-write-001", "payload": {"name": "Synthetic session agency"}}
    with pytest.raises(MCPAuthError):
        await operation.execute(**arguments)
    await configure(session, actor, 1, mcp_write_enabled=True)
    first = await operation.execute(**arguments)
    await session.commit()
    assert (await operation.execute(**arguments))["operation_id"] == first["operation_id"]
    assert await session.scalar(select(func.count()).select_from(AgencyModel)) == 1
    await configure(session, actor, 2)
    with pytest.raises(MCPAuthError):
        await operation.execute(**arguments)
    # Delayed work uses the same live capability gate without a browser token.
    with pytest.raises(MCPAuthError):
        await require_tool_access(session, settings, grant.id, POLICY.name, "mcp:change")


@pytest.mark.parametrize("restriction", ["global_read", "global_write", "section", "tool", "deployment"])
async def test_internal_identity_does_not_expand_global_mcp_ceiling(assistant_authority, restriction):
    session, settings, actor, claims, *_ = assistant_authority
    grant = await ensure_assistant_authority(session, settings, actor, claims)
    token = await private_token(session, settings, grant)
    await configure(session, actor, 1, mcp_write_enabled=True)
    control = await session.get(MCPControlModel, 1)
    if restriction == "global_read":
        control.read_enabled = False
    elif restriction == "global_write":
        control.write_enabled = False
    elif restriction == "section":
        control.allowed_write_sections = []
    elif restriction == "tool":
        control.allowed_write_tools = []
    else:
        settings = settings.model_copy(update={"mcp": settings.mcp.model_copy(update={"read_only_mode": True})})
    await session.commit()
    with pytest.raises(MCPAuthError):
        if restriction == "global_read":
            await MCPAuthorizationService(session, settings).verify_access(token, "mcp:read")
        else:
            await require_tool_access(session, settings, grant.id, POLICY.name, "mcp:change")


async def test_disabling_ai_does_not_revoke_or_restrict_external_mcp(assistant_authority):
    session, settings, actor, _, _, external, tokens = assistant_authority
    await configure(session, actor, 1, enabled=False)
    principal = await MCPAuthorizationService(session, settings).verify_access(tokens[0], "mcp:change")
    assert principal.grant_id == external[0].id
    assert external[0].revoked_at is None


async def test_reserved_identity_cannot_authorize_exchange_refresh_or_issue_oauth_tokens(assistant_authority):
    session, settings, actor, claims, *_ = assistant_authority
    grant = await ensure_assistant_authority(session, settings, actor, claims)
    auth, now = MCPAuthorizationService(session, settings), datetime.now(UTC)
    code = MCPAuthorizationCodeModel(code_hash=auth.digest("synthetic-code"), grant_id=grant.id,
        redirect_uri="http://127.0.0.1:8765/callback", code_challenge="A" * 43, expires_at=now + timedelta(minutes=5))
    refresh = MCPTokenModel(token_hash=auth.digest("synthetic-refresh"), grant_id=grant.id,
        kind="refresh", expires_at=now + timedelta(minutes=5))
    session.add_all([code, refresh])
    await session.commit()
    before = await session.scalar(select(func.count()).select_from(MCPTokenModel))
    calls = [
        lambda: auth.authorize(user_id=actor.id, security_version=actor.session_version, mfa_at=now,
            client_id=ASSISTANT_CLIENT_ID, redirect_uri=code.redirect_uri, resource=settings.mcp.resource,
            challenge="A" * 43, scopes=["mcp:read"], name="Invalid external request"),
        lambda: auth.exchange_code(code="synthetic-code", verifier="A" * 43,
            client_id=ASSISTANT_CLIENT_ID, redirect_uri=code.redirect_uri, resource=settings.mcp.resource),
        lambda: auth.refresh(token="synthetic-refresh", client_id=ASSISTANT_CLIENT_ID, resource=settings.mcp.resource),
        lambda: auth.issue_pair(grant, now),
    ]
    for call in calls:
        with pytest.raises(MCPAuthError):
            await call()
    assert code.consumed_at is None and refresh.consumed_at is None and grant.revoked_at is None
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == before
