"""Independent live section permissions and unchanged issued OAuth envelopes."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import (
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationService,
)
from app.application.mcp.permissions import require_tool_access
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.mcp_permission_schemas import MCPPermissionsUpdate
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


async def global_save(fixture, **values):
    client, _, _, _, _, dashboard = fixture
    current = (await client.get("/api/v1/admin/mcp/permissions", headers={"Authorization": f"Bearer {dashboard}"})).json()
    body = {"expected_revision": current["permission_revision"], "read_enabled": True, "write_enabled": True,
            "allowed_read_sections": ["all_groups", "old_data", "whatsapp"],
            "allowed_write_sections": ["group_links"], "allowed_write_tools": ["create_group"], **values}
    return await client.put("/api/v1/admin/mcp/permissions", headers={"Authorization": f"Bearer {dashboard}"}, json=body)


async def device_save(fixture, grant, **values):
    client, _, _, _, _, dashboard = fixture
    await fixture[1].refresh(grant)
    return await client.put(f"/api/v1/admin/mcp/connections/{grant.id}/permissions",
        headers={"Authorization": f"Bearer {dashboard}"}, json={"expected_revision": grant.permission_revision,
            "read_enabled": True, "write_enabled": True, "allowed_read_sections": None,
            "allowed_write_sections": ["group_links"], **values})


async def connection(fixture, scopes=None):
    _, tokens = await connect(fixture, scopes=scopes or ["mcp:read", "mcp:change"])
    grant = await fixture[1].scalar(select(MCPGrantModel).order_by(MCPGrantModel.created_at.desc()))
    return grant, tokens["access_token"]


def operation(session, settings, callback):
    return MCPOperationService(session, settings, [MCPDatabaseOperation(
        MCPToolPolicy("create_group", MCPCapability.CHANGE, frozenset({"create"})), callback)])


async def execute(service, token, key="permission-test-stable-key"):
    return await service.execute(access_token=token, operation_name="create_group", idempotency_key=key, payload={"name": "synthetic"})


async def test_old_grant_defaults_preserve_reads_and_deny_all_effect_scopes(mcp_fixture):
    grant, token = await connection(mcp_fixture, ["mcp:read", "mcp:change", "mcp:export", "mcp:upload", "mcp:communicate"])
    _, session, settings, _, _, _ = mcp_fixture
    assert grant.read_enabled is True and grant.write_enabled is False
    assert grant.allowed_read_sections is None and grant.allowed_write_sections == []
    control = await session.get(MCPControlModel, 1)
    assert control.read_enabled is True and control.write_enabled is False
    authorization = MCPAuthorizationService(session, settings)
    await authorization.verify_access(token, "mcp:read")
    for capability in ("mcp:change", "mcp:export", "mcp:upload", "mcp:communicate"):
        with pytest.raises(MCPAuthError, match="write_access_denied"):
            await authorization.verify_access(token, capability)
    assert set(grant.capabilities) == {"mcp:read", "mcp:change", "mcp:export", "mcp:upload", "mcp:communicate"}


async def test_independent_read_write_toggles_and_other_connection_unchanged(mcp_fixture):
    first, first_token = await connection(mcp_fixture)
    second, second_token = await connection(mcp_fixture)
    assert (await global_save(mcp_fixture)).status_code == 200
    assert (await device_save(mcp_fixture, first, read_enabled=False)).status_code == 200
    session, settings = mcp_fixture[1:3]
    callback = AsyncMock(return_value=MCPDatabaseResult({"created": True}))
    service = operation(session, settings, callback)
    with pytest.raises(MCPAuthError, match="read_access_denied"):
        await MCPAuthorizationService(session, settings).verify_access(first_token, "mcp:read")
    receipt = await execute(service, first_token)
    await session.commit()
    assert receipt["data"] == {"created": True} and callback.await_count == 1
    await MCPAuthorizationService(session, settings).verify_access(second_token, "mcp:read")
    with pytest.raises(MCPAuthError, match="write_access_denied"):
        await execute(service, second_token, key="independent-second-device")
    assert second.write_enabled is False and second.read_enabled is True
    assert (await device_save(mcp_fixture, first, read_enabled=True, write_enabled=False)).status_code == 200
    with pytest.raises(MCPAuthError, match="write_access_denied"):
        await execute(service, first_token)
    assert callback.await_count == 1


async def test_mixed_mode_always_enforces_global_read_sections_before_service(mcp_fixture, monkeypatch):
    from app.application.mcp.group_reads import MCPGroupReadService

    client = mcp_fixture[0]
    session = mcp_fixture[1]
    control = await session.get(MCPControlModel, 1)
    control.allowed_read_sections = []
    await session.commit()
    _, token = await connection(mcp_fixture)
    callback = AsyncMock(return_value={"items": [], "has_more": False, "next_cursor": None})
    monkeypatch.setattr(MCPGroupReadService, "list_groups", callback)
    denied = await call_mcp(client, token, name="list_groups")
    assert "access_denied" in denied.text and "required_sections" in denied.text
    callback.assert_not_awaited()
    assert (await global_save(mcp_fixture)).status_code == 200
    accepted = await call_mcp(client, token, name="list_groups")
    assert "access_denied" not in accepted.text
    assert callback.await_count == 1


async def test_device_read_sections_narrow_global_union_and_dynamic_dashboard(mcp_fixture):
    grant, token = await connection(mcp_fixture)
    assert (await global_save(mcp_fixture, allowed_read_sections=["settings", "all_groups", "whatsapp", "old_data"])).status_code == 200
    assert (await device_save(mcp_fixture, grant, allowed_read_sections=["all_groups"], write_enabled=False)).status_code == 200
    client = mcp_fixture[0]
    denied = await call_mcp(client, token, name="read_dashboard_view", arguments={"view": "platform_settings"})
    assert "access_denied" in denied.text and "settings" in denied.text
    denied_group = await call_mcp(client, token, name="list_groups")
    assert "access_denied" in denied_group.text
    assert (await device_save(mcp_fixture, grant, allowed_read_sections=None, write_enabled=False)).status_code == 200
    accepted = await call_mcp(client, token, name="read_dashboard_view", arguments={"view": "platform_settings"})
    assert "access_denied" not in accepted.text and "reviewed_dashboard_read" in accepted.text


@pytest.mark.parametrize("boundary", ["global_sections", "device_sections", "tool", "unknown", "global_write"])
async def test_write_denials_precede_mutation_and_receipt_creation(mcp_fixture, boundary):
    grant, token = await connection(mcp_fixture)
    assert (await global_save(mcp_fixture)).status_code == 200
    assert (await device_save(mcp_fixture, grant)).status_code == 200
    client, session, settings, _, _, _ = mcp_fixture
    if boundary == "global_sections":
        assert (await global_save(mcp_fixture, allowed_write_sections=[], allowed_write_tools=[])).status_code == 200
    elif boundary == "device_sections":
        assert (await device_save(mcp_fixture, grant, allowed_write_sections=[])).status_code == 200
    elif boundary == "tool":
        assert (await global_save(mcp_fixture, allowed_write_tools=[])).status_code == 200
    elif boundary == "global_write":
        assert (await global_save(mcp_fixture, write_enabled=False)).status_code == 200
    callback = AsyncMock(return_value=MCPDatabaseResult({"created": True}))
    with pytest.raises(MCPAuthError):
        if boundary == "unknown":
            await require_tool_access(session, settings, grant.id, "invented_create_group", "mcp:change")
        else:
            await execute(operation(session, settings, callback), token)
    callback.assert_not_awaited()
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_completed_retry_and_inspect_recheck_current_tool_authority(mcp_fixture):
    grant, token = await connection(mcp_fixture)
    assert (await global_save(mcp_fixture)).status_code == 200
    assert (await device_save(mcp_fixture, grant)).status_code == 200
    session, settings = mcp_fixture[1:3]
    callback = AsyncMock(return_value=MCPDatabaseResult({"created": True}))
    service = operation(session, settings, callback)
    receipt = await execute(service, token)
    await session.commit()
    assert (await global_save(mcp_fixture, allowed_write_tools=[])).status_code == 200
    for call in (lambda: execute(service, token), lambda: service.inspect(access_token=token, operation_id=uuid.UUID(receipt["operation_id"]))):
        with pytest.raises(MCPAuthError, match="write_tool_denied"):
            await call()
    assert callback.await_count == 1


async def test_dynamic_native_source_sections_are_mandatory_and_exact(mcp_fixture):
    grant, _ = await connection(mcp_fixture, ["mcp:read", "mcp:upload", "mcp:export"])
    assert (await global_save(mcp_fixture, allowed_write_sections=["document_delivery"],
                             allowed_write_tools=["create_native_upload"])).status_code == 200
    assert (await device_save(mcp_fixture, grant, allowed_write_sections=["document_delivery"])).status_code == 200
    session, settings = mcp_fixture[1:3]
    for sections in (None, frozenset(), frozenset({"exports"}), frozenset({"group_excel_imports"})):
        with pytest.raises(MCPAuthError, match="write_section_denied"):
            await require_tool_access(session, settings, grant.id, "create_native_upload", "mcp:upload", required_sections=sections)
    await require_tool_access(session, settings, grant.id, "create_native_upload", "mcp:upload",
                              required_sections=frozenset({"document_delivery"}))


async def test_dynamic_workforce_role_is_rechecked_on_receipt_inspection(mcp_fixture):
    grant, token = await connection(mcp_fixture)
    assert (await global_save(mcp_fixture, allowed_write_sections=["staff"],
                             allowed_write_tools=["create_workforce_account"])).status_code == 200
    assert (await device_save(mcp_fixture, grant, allowed_write_sections=["staff"])).status_code == 200
    session, settings = mcp_fixture[1:3]
    callback = AsyncMock(return_value=MCPDatabaseResult({"account_type": "staff"}))
    service = MCPOperationService(session, settings, [MCPDatabaseOperation(
        MCPToolPolicy("create_workforce_account", MCPCapability.CHANGE, frozenset({"create"})), callback,
        permission_sections=lambda data: frozenset({{"staff": "staff", "manager": "manager"}[data["account_type"]]}))])
    receipt = await service.execute(access_token=token, operation_name="create_workforce_account", idempotency_key="staff-role-permission-key",
                                    payload={"account_type": "staff"})
    await session.commit()
    assert (await service.inspect(access_token=token, operation_id=uuid.UUID(receipt["operation_id"])))["operation"] == "create_workforce_account"
    with pytest.raises(MCPAuthError, match="write_section_denied"):
        await service.execute(access_token=token, operation_name="create_workforce_account", idempotency_key="manager-role-permission-key", payload={"account_type": "manager"})
    assert callback.await_count == 1


async def test_no_silent_scope_expansion_and_stale_revision_has_no_audit_or_save(mcp_fixture):
    grant, _ = await connection(mcp_fixture, ["mcp:read"])
    saved_scopes = list(grant.capabilities)
    rejected = await device_save(mcp_fixture, grant)
    assert rejected.status_code == 409 and "Reconnect" in rejected.text
    assert grant.capabilities == saved_scopes and grant.write_enabled is False
    assert (await global_save(mcp_fixture)).status_code == 200
    stale = await global_save(mcp_fixture, expected_revision=1, allowed_read_sections=[])
    assert stale.status_code == 409
    control = await mcp_fixture[1].get(MCPControlModel, 1)
    assert control.allowed_read_sections == ["all_groups", "old_data", "whatsapp"] and control.read_access_revision == 2
    assert await mcp_fixture[1].scalar(select(func.count()).select_from(AuditLogModel).where(AuditLogModel.action == "mcp.permissions_changed")) == 1
    assert (await AuditLogRepository(mcp_fixture[1]).verify_chain(None)).valid


async def test_global_pause_and_disabled_deleted_connections_cannot_be_bypassed(mcp_fixture):
    grant, token = await connection(mcp_fixture)
    assert (await global_save(mcp_fixture)).status_code == 200
    assert (await device_save(mcp_fixture, grant)).status_code == 200
    session, settings = mcp_fixture[1:3]
    grant.enabled = False
    await session.commit()
    with pytest.raises(MCPAuthError, match="access_denied"):
        await execute(operation(session, settings, AsyncMock()), token)
    # Saving a device permission does not undo the independent pause flag.
    assert (await device_save(mcp_fixture, grant)).status_code == 200 and grant.enabled is False
    grant.revoked_at, grant.revocation_reason = datetime.now(UTC), "administrator_removed"
    await session.commit()
    assert (await device_save(mcp_fixture, grant)).status_code == 409


@pytest.mark.parametrize("guard", ["anonymous", "cookie_csrf", "stale_mfa", "role"])
async def test_permission_mutations_require_superadmin_csrf_and_recent_mfa(mcp_fixture, guard):
    client, session, _, user, _, dashboard = mcp_fixture
    headers = {"Authorization": f"Bearer {dashboard}"}
    if guard == "anonymous":
        headers = {}
    elif guard == "cookie_csrf":
        client.cookies.set("access_token", dashboard)
        headers = {"Origin": "https://attacker.example"}
    elif guard == "role":
        user.role = "agency_staff"
        await session.commit()
    elif guard == "stale_mfa":
        stale, _ = await issue_dashboard_access(session, user.id, "super_admin", session_version=1,
            authentication_methods=("pwd", "totp"), mfa_authenticated_at=datetime.now(UTC) - timedelta(minutes=11))
        headers = {"Authorization": f"Bearer {stale}"}
    response = await client.put("/api/v1/admin/mcp/permissions", headers=headers,
        json={"expected_revision": 1, "read_enabled": True, "write_enabled": False,
              "allowed_read_sections": [], "allowed_write_sections": []})
    assert response.status_code in {401, 403}
    control = await session.get(MCPControlModel, 1)
    assert control.read_access_revision == 1 and control.write_enabled is False


def test_global_section_switches_derive_bounded_tool_allowlist_and_reject_unknowns():
    base = {"expected_revision": 1, "read_enabled": True, "write_enabled": True,
            "allowed_read_sections": [], "allowed_write_sections": ["all_groups"]}
    value = MCPPermissionsUpdate.model_validate(base)
    assert "correct_client_details" in value.allowed_write_tools and "create_rooming_hotel" not in value.allowed_write_tools
    for changes in ({"allowed_write_tools": ["invented"]}, {"allowed_write_tools": ["create_rooming_hotel"]},
                    {"write_enabled": "true"}, {"allowed_write_sections": ["server_control"]}):
        with pytest.raises(ValidationError):
            MCPPermissionsUpdate.model_validate({**base, **changes})
