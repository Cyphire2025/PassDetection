"""Exercise per-device discovery and status through the actual MCP SDK transport."""

import json

import pytest
from sqlalchemy import select

from app.domain.mcp_policy import CAPABILITIES
from app.domain.mcp_read_sections import READ_TOOL_SECTIONS
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture

WRITE_TOOLS = [
    "create_group",
    "create_native_upload",
    "create_native_download",
    "inspect_native_transfer",
    "prepare_whatsapp_document_delivery",
    "confirm_whatsapp_document_delivery",
    "upload_document_pdf",
    "upload_group_workbook",
    "upload_contact_workbook",
    "download_export",
    "prepare_excel_export",
]


async def configure(fixture, *, scopes=None, read_sections=None, write_sections=None):
    fixture[2].mcp.enabled_capabilities = sorted(CAPABILITIES - {"mcp:diagnose"})
    control = await fixture[1].get(MCPControlModel, 1)
    control.read_enabled, control.write_enabled = True, True
    control.allowed_read_sections = ["all_groups", "tour_ops"]
    control.allowed_write_sections = ["group_links", "document_delivery", "exports"]
    control.allowed_write_tools = WRITE_TOOLS
    await fixture[1].commit()
    selected = sorted(CAPABILITIES - {"mcp:diagnose"}) if scopes is None else scopes
    _, tokens = await connect(
        fixture,
        scopes=selected,
        permissions={
            "read_enabled": "mcp:read" in selected,
            "write_enabled": bool(set(selected) - {"mcp:read"}),
            "allowed_read_sections": ["all_groups"] if read_sections is None else read_sections,
            "allowed_write_sections": ["document_delivery"]
            if write_sections is None
            else write_sections,
        },
    )
    grant = await fixture[1].scalar(select(MCPGrantModel))
    return tokens["access_token"], control, grant


async def discover(fixture, token):
    response = await fixture[0].post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        },
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 200, response.text
    return {row["name"] for row in response.json()["result"]["tools"]}


async def status(fixture, token):
    response = await call_mcp(fixture[0], token)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError"), result
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


async def test_real_sdk_status_and_listing_use_same_exact_device_policy(mcp_fixture):
    token, _, grant = await configure(mcp_fixture)
    visible = await discover(mcp_fixture, token)
    assert {
        "connection_status",
        "list_group_passports",
        "create_native_upload",
        "prepare_whatsapp_document_delivery",
        "confirm_whatsapp_document_delivery",
    } <= visible
    assert not {"get_passenger_qr", "create_group", "create_native_download"} & visible
    current = await status(mcp_fixture, token)
    assert set(current["implemented_tools"]) == visible
    assert current["allowed_read_sections"] == ["all_groups"]
    assert current["allowed_write_sections"] == ["document_delivery"]
    assert current["effective_capabilities"] == ["mcp:communicate", "mcp:read", "mcp:upload"]
    assert set(current["capabilities"]) == CAPABILITIES - {
        "mcp:diagnose"
    }  # OAuth envelope is retained.
    assert current["export_families"] == [] and current["export_source_byte_limit"] == 0
    assert current["device_permission_revision"] == grant.permission_revision


@pytest.mark.parametrize(
    "scope,sections,available",
    [
        ("mcp:upload", ["exports"], False),
        ("mcp:export", ["document_delivery"], False),
        ("mcp:upload", ["document_delivery"], True),
        ("mcp:export", ["exports"], True),
    ],
)
async def test_native_inspection_requires_matching_scope_and_file_lane(
    mcp_fixture, scope, sections, available
):
    token, _, _ = await configure(mcp_fixture, scopes=["mcp:read", scope], write_sections=sections)
    visible = await discover(mcp_fixture, token)
    assert ("inspect_native_transfer" in visible) is available
    assert (scope in (await status(mcp_fixture, token))["effective_capabilities"]) is available


@pytest.mark.parametrize("narrowing", ["global", "device", "sections", "tools", "release"])
async def test_next_real_discovery_and_status_reflect_saved_write_narrowing(mcp_fixture, narrowing):
    token, control, grant = await configure(mcp_fixture)
    assert "confirm_whatsapp_document_delivery" in await discover(mcp_fixture, token)
    if narrowing == "global":
        control.write_enabled = False
    elif narrowing == "device":
        grant.write_enabled = False
    elif narrowing == "sections":
        grant.allowed_write_sections = []
    elif narrowing == "tools":
        control.allowed_write_tools = []
    else:
        mcp_fixture[2].mcp.read_only_mode = True
    await mcp_fixture[1].commit()
    visible = await discover(mcp_fixture, token)
    current = await status(mcp_fixture, token)
    assert not set(WRITE_TOOLS) & visible
    assert set(current["implemented_tools"]) == visible
    assert current["effective_capabilities"] == ["mcp:read"]
    assert current["allowed_write_tools"] == []


async def test_admin_inventory_reports_global_policy_without_claiming_device_authority(mcp_fixture):
    token, control, grant = await configure(mcp_fixture)
    response = await mcp_fixture[0].get(
        "/api/v1/admin/mcp/inventory", headers={"Authorization": f"Bearer {mcp_fixture[5]}"}
    )
    assert response.status_code == 200, response.text
    inventory = response.json()
    rows = {row["name"]: row for row in inventory["tools"]}
    assert inventory["permission_scope"] == "global_deployment"
    assert rows["create_group"]["available"] is True
    assert "create_group" not in await discover(mcp_fixture, token)
    control.allowed_write_tools = ["create_native_upload", "upload_document_pdf"]
    control.allowed_write_sections = ["document_delivery"]
    await mcp_fixture[1].commit()
    inventory = (
        await mcp_fixture[0].get(
            "/api/v1/admin/mcp/inventory", headers={"Authorization": f"Bearer {mcp_fixture[5]}"}
        )
    ).json()
    rows = {row["name"]: row for row in inventory["tools"]}
    assert rows["create_group"]["deployment_available"] is True
    assert rows["create_group"]["available"] is False
    assert rows["create_native_upload"]["available_section_choices"] == ["document_delivery"]
    assert inventory["effective_capabilities"] == ["mcp:read", "mcp:upload"]
    assert grant.allowed_write_sections == ["document_delivery"]


async def test_corrupt_device_policy_fails_closed_at_native_listing(mcp_fixture):
    token, _, grant = await configure(mcp_fixture)
    grant.allowed_write_sections = {"document_delivery": True}
    await mcp_fixture[1].commit()
    assert await discover(mcp_fixture, token) == set()


@pytest.mark.parametrize("boundary", ["device", "global"])
async def test_real_read_toggle_preserves_independent_write_discovery(mcp_fixture, boundary):
    token, control, grant = await configure(mcp_fixture)
    if boundary == "device":
        grant.read_enabled = False
    else:
        control.read_enabled = False
    await mcp_fixture[1].commit()
    visible = await discover(mcp_fixture, token)
    assert not set(READ_TOOL_SECTIONS) & visible
    assert {"create_native_upload", "confirm_whatsapp_document_delivery"} <= visible
    result = (await call_mcp(mcp_fixture[0], token)).json()["result"]["structuredContent"]
    assert result["error"] == "access_denied"


async def test_diagnostics_are_explicit_observations_with_read_policy_and_separate_scope(
    mcp_fixture,
):
    _, tokens = await connect(mcp_fixture, scopes=["mcp:read", "mcp:diagnose"])
    token = tokens["access_token"]
    assert "inspect_diagnostics" in await discover(mcp_fixture, token)
    current = await status(mcp_fixture, token)
    assert "mcp:diagnose" in current["effective_capabilities"]
    assert "inspect_diagnostics" not in current["allowed_write_tools"]
    control = await mcp_fixture[1].get(MCPControlModel, 1)
    control.read_enabled = False
    await mcp_fixture[1].commit()
    assert "inspect_diagnostics" not in await discover(mcp_fixture, token)
    result = (
        await call_mcp(
            mcp_fixture[0], token, name="inspect_diagnostics", arguments={"sources": ["audit"]}
        )
    ).json()["result"]["structuredContent"]
    assert result["error"] == "access_denied"


async def test_inventory_dynamic_choices_respect_release_scope_ceiling(mcp_fixture):
    await configure(mcp_fixture)
    mcp_fixture[2].mcp.enabled_capabilities = ["mcp:read", "mcp:export"]
    response = await mcp_fixture[0].get(
        "/api/v1/admin/mcp/inventory", headers={"Authorization": f"Bearer {mcp_fixture[5]}"}
    )
    rows = {row["name"]: row for row in response.json()["tools"]}
    assert rows["create_native_upload"]["available_section_choices"] == []
    assert rows["inspect_native_transfer"]["available_section_choices"] == ["exports"]
    assert rows["create_native_download"]["available_section_choices"] == ["exports"]
    assert rows["create_workforce_account"]["available_section_choices"] == []


@pytest.mark.parametrize(
    "missing", ["upload_document_pdf", "download_export", "prepare_excel_export", "family"]
)
async def test_native_creation_discovery_rechecks_canonical_source_gates(mcp_fixture, missing):
    token, control, _ = await configure(
        mcp_fixture, write_sections=["document_delivery", "exports"]
    )
    assert {"create_native_upload", "create_native_download"} <= await discover(mcp_fixture, token)
    if missing == "family":
        mcp_fixture[2].mcp.export_families = []
    else:
        control.allowed_write_tools = [
            name for name in control.allowed_write_tools if name != missing
        ]
    await mcp_fixture[1].commit()
    visible = await discover(mcp_fixture, token)
    if missing == "upload_document_pdf":
        assert "create_native_upload" not in visible
        assert "create_native_download" in visible
    else:
        assert "create_native_download" not in visible
        assert "create_native_upload" in visible


async def test_dual_scope_transfer_inspection_reports_only_the_effective_file_lane(mcp_fixture):
    token, _, _ = await configure(
        mcp_fixture, scopes=["mcp:read", "mcp:upload", "mcp:export"], write_sections=["exports"]
    )
    assert "inspect_native_transfer" in await discover(mcp_fixture, token)
    assert (await status(mcp_fixture, token))["effective_capabilities"] == [
        "mcp:export",
        "mcp:read",
    ]
