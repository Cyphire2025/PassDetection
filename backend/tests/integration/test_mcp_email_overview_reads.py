"""Canonical readiness/count parity and bounded private read observations."""

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import event, func, select

from app.application.mcp import email_overview_reads
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.email_overview_reads import (
    EmailOverviewReadError,
    MCPEmailOverviewReadService,
)
from app.application.use_cases.email_integrations.overview import (
    email_readiness,
    provider_configured,
)
from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailConnectionModel,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.repositories.email_summary_repository import (
    SUMMARY_FIELDS,
    EmailSummaryRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import email_integration_activity, email_integration_connections
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.mcp_email_overview_fixtures import PER_COHORT, seed_email_overview


@pytest.fixture
async def overview(operations_fixture):
    f = operations_fixture
    data = await seed_email_overview(f[0], f[2])
    f[3][0].capabilities = ["mcp:read"]
    await f[0].commit()
    return f, data


def principal(f):
    grant = f[3][0]
    return MCPPrincipal(grant.id, f[2].id, grant.client_id, tuple(grant.capabilities), grant.expires_at, grant.resource)


async def test_summary_exact_website_parity_no_agency_and_inactive_agency(overview):
    f, data = overview
    service = MCPEmailOverviewReadService(f[0], f[1])
    for agency_id in (None, data.agencies[0].id, data.agencies[1].id):
        f[2].agency_id = agency_id
        await f[0].flush()
        actor = await UserRepository(f[0]).get_by_id(f[2].id)
        web = await email_integration_activity.email_integration_summary(actor, f[0])
        result = await service.get_summary(principal(f))
        assert {name: result[name] for name in SUMMARY_FIELDS} == web.model_dump() == data.expected
        assert result["period_start_utc"] == data.today.isoformat()
        assert result["mailbox_scope"] == "personal_owner_only" and result["completeness"] == "complete"
        assert result["consistency"] == {"mode": "live_multi_query", "snapshot_guaranteed": False}
        assert "SECRET" not in json.dumps(result) and "PRIVATE" not in json.dumps(result)
    assert await f[0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_seven_scalar_counts_no_orm_content_or_ciphertexts(overview):
    f, data = overview
    statements, hydrated = [], []
    def statement(_conn, _cursor, sql, *_args):
        statements.append(sql.lower())
    def loaded(*_args):
        hydrated.append(True)
    engine = f[0].bind.sync_engine
    event.listen(engine, "before_cursor_execute", statement)
    for model in (EmailConnectionModel, EmailArtifactDocumentModel):
        event.listen(model, "load", loaded)
        event.listen(model, "refresh", loaded)
    try:
        await MCPEmailOverviewReadService(f[0], f[1]).get_summary(principal(f))
    finally:
        event.remove(engine, "before_cursor_execute", statement)
        for model in (EmailConnectionModel, EmailArtifactDocumentModel):
            event.remove(model, "load", loaded)
            event.remove(model, "refresh", loaded)
    business = [sql for sql in statements if "from email_" in sql]
    assert len(business) == 7 and all(sql.startswith("select count(") for sql in business)
    assert len(statements) == 11 and not hydrated
    projections = " ".join(sql.split(" from ")[0].split("\nfrom ")[0] for sql in business)
    assert not any(word in projections for word in ("ciphertext", "body", "subject", "match_evidence", "storage", "email_address"))
    assert all("owner_user_id =" in sql for sql in business)


async def test_website_non_superadmin_agency_scope_and_missing_agency_contract(overview):
    f, data = overview
    actor = await UserRepository(f[0]).get_by_id(f[2].id)
    actor.role, actor.agency_id = UserRole.AGENCY_STAFF, data.agencies[0].id
    assert (await email_integration_activity.email_integration_summary(actor, f[0])).model_dump() == PER_COHORT
    actor.agency_id = None
    with pytest.raises(HTTPException) as caught:
        await email_integration_activity.email_integration_summary(actor, f[0])
    assert caught.value.status_code == 403


@pytest.mark.parametrize("enabled,sync,ai,key,notify,expected", [
    (True, True, True, "SECRET_KEY", True, True), (False, True, True, "SECRET_KEY", True, False),
    (True, False, True, "SECRET_KEY", True, False), (True, True, False, "SECRET_KEY", True, False),
    (True, True, True, " ", True, False), (True, True, True, "SECRET_KEY", False, True),
])
async def test_status_uses_exact_runtime_readiness_without_secrets(operations_fixture, monkeypatch, enabled, sync, ai, key, notify, expected):
    f = operations_fixture
    f[3][0].capabilities = ["mcp:read"]
    await f[0].commit()
    settings = f[1].model_copy(update=dict(email_integrations_enabled=enabled, email_sync_enabled=sync,
        email_ai_enabled=ai, google_api_key=SecretStr(key), email_ai_notifications_enabled=notify,
        gmail_oauth_client_id="SECRET_ID", gmail_oauth_client_secret=SecretStr("SECRET_GMAIL"),
        gmail_oauth_redirect_uri="https://private.example/callback", email_token_encryption_key=SecretStr("SECRET_ENCRYPTION"),
        outlook_oauth_client_id=None))
    monkeypatch.setattr(email_integration_connections, "get_settings", lambda: settings)
    expected_web = (await email_integration_connections.email_integration_status(f[2])).model_dump()
    result = await MCPEmailOverviewReadService(f[0], settings).get_status(principal(f))
    assert {key: result[key] for key in expected_web} == expected_web == email_readiness(settings)
    assert result["ai_enabled"] is expected and result["ai_notifications_enabled"] is (expected and notify)
    assert result["providers"] == [{"provider": "gmail", "label": "Gmail", "configured": True},
        {"provider": "outlook", "label": "Microsoft Outlook", "configured": False}]
    assert "SECRET" not in json.dumps(result) and "private.example" not in json.dumps(result)


@pytest.mark.parametrize("provider", ["gmail", "outlook", "unknown"])
def test_configuration_presence_independent_and_whitespace_secrets(test_settings, provider):
    settings = test_settings.model_copy(update=dict(gmail_oauth_client_id="present", outlook_oauth_client_id="present",
        gmail_oauth_client_secret=SecretStr(" "), outlook_oauth_client_secret=SecretStr("present"),
        gmail_oauth_redirect_uri="https://example.test", outlook_oauth_redirect_uri="https://example.test",
        email_token_encryption_key=SecretStr("present")))
    assert provider_configured(settings, provider) is (provider == "outlook")
    settings.email_token_encryption_key = SecretStr(" ")
    assert provider_configured(settings, provider) is False


@pytest.mark.parametrize("method", ["get_status", "get_summary"])
async def test_complete_envelope_bound_and_deadline(overview, monkeypatch, method):
    f, _ = overview
    service = MCPEmailOverviewReadService(f[0], f[1])
    result = await getattr(service, method)(principal(f))
    monkeypatch.setattr(email_overview_reads, "MAX_EMAIL_OVERVIEW_RESPONSE_BYTES", len(json.dumps(result).encode()) + 1)
    with pytest.raises(EmailOverviewReadError, match="email_overview_limit"):
        await getattr(service, method)(principal(f))
    monkeypatch.setattr(email_overview_reads, "MAX_EMAIL_OVERVIEW_RESPONSE_BYTES", 8192)
    monkeypatch.setattr(email_overview_reads, "EMAIL_OVERVIEW_TIMEOUT_SECONDS", 0.01)
    async def slow(_principal):
        await asyncio.sleep(1)
    monkeypatch.setattr(service, "_actor", slow)
    with pytest.raises(EmailOverviewReadError, match="email_overview_busy"):
        await getattr(service, method)(principal(f))


@pytest.mark.parametrize("bad_count", [-1, True, 2**63])
async def test_invalid_count_fails_whole_observation(overview, monkeypatch, bad_count):
    f, data = overview
    monkeypatch.setattr(EmailSummaryRepository, "summary", AsyncMock(return_value={**data.expected, "pending_review": bad_count}))
    with pytest.raises(EmailOverviewReadError, match="email_overview_limit"):
        await MCPEmailOverviewReadService(f[0], f[1]).get_summary(principal(f))


async def test_stale_principal_cannot_read_with_foreign_user_binding(overview):
    f, data = overview
    with pytest.raises(MCPAuthError):
        await MCPEmailOverviewReadService(f[0], f[1]).get_summary(replace(principal(f), user_id=data.other.id))
