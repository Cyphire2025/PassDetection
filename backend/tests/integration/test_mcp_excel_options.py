"""Canonical website option parity, authority and read-only SDK/HTTP behavior."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.application.mcp import excel_options
from app.application.mcp.artifacts import ArtifactError, MCPArtifactService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.excel_options import ExcelExportOptionsRequest, MCPExcelOptionsService
from app.application.mcp.exports import MCPExcelExportService
from app.application.use_cases.passports.excel_export_options import project_excel_export_options
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportExportHistoryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes.excel_exports import (
    export_options_support,
    get_passport_group_export_fields,
)
from app.presentation.api.v1.routes.passport_routes.selected_exports import (
    get_selected_groups_export_fields,
)
from app.presentation.api.v1.schemas.passport_schemas import ExportSelectedGroupsRequest
from app.presentation.mcp.excel_options_tools import excel_options_support
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


@pytest.fixture(autouse=True)
def no_generation(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Option discovery must not prepare, render or access storage")

    monkeypatch.setattr(MCPArtifactService, "storage", property(forbidden))
    monkeypatch.setattr(MCPExcelExportService, "prepare", forbidden)
    monkeypatch.setattr(PassportExcelExporter, "export_group", forbidden)


async def imported_source(session, group, fields, *, removed=False):
    broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(), agency_id=group.agency_id, name="Synthetic source"
    )
    session.add(broadcast)
    await session.flush()
    session.add(
        ClientGroupWhatsAppBroadcastLinkModel(
            id=uuid.uuid4(),
            agency_id=group.agency_id,
            client_group_id=group.id,
            broadcast_group_id=broadcast.id,
        )
    )
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        broadcast_group_id=broadcast.id,
        name="PRIVATE-PERSON",
        phone_number="+919888000001",
        normalized_phone_number="+919888000001",
        imported_fields=fields,
        removed_at=datetime.now(UTC) if removed else None,
    )
    session.add(recipient)
    await session.flush()
    return recipient


async def inspect(f, groups=None, selection="group"):
    return await MCPExcelOptionsService(f.session, f.settings, excel_options_support()).inspect(
        f.principal,
        ExcelExportOptionsRequest(
            agency_id=f.agency.id, group_ids=groups or [f.group.id], selection=selection
        ),
    )


async def no_business_effects(session):
    for model in (
        MCPArtifactModel,
        MCPOperationModel,
        PassportExportHistoryModel,
        WhatsAppMessageLogModel,
    ):
        assert await session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("kind", ["empty", "legacy_airport", "pending", "agency", "removed"])
async def test_group_options_match_website_without_passports_or_generated_objects(artifacts, kind):
    f = artifacts
    f.group.import_only = True
    f.group.agency_dealership_name_enabled = kind == "agency"
    if kind == "legacy_airport":
        f.group.departure_cities = ["Delhi"]
    if kind in {"pending", "agency", "removed"}:
        await imported_source(
            f.session,
            f.group,
            {
                "Zone": "PRIVATE-WEST",
                "Office": "PRIVATE-OFFICE",
                "Email": "private@example.test",
                "Agency Name": "PRIVATE-AGENCY",
                "source_row": 1,
            },
            removed=kind == "removed",
        )
    await f.session.commit()
    result = await inspect(f)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    website = await get_passport_group_export_fields(
        f.group.id, current_user=replace(actor, agency_id=f.agency.id), session=f.session
    )
    expected = website.model_dump(mode="json")
    assert {key: result[key] for key in expected if key != "group_id"} == {
        key: value for key, value in expected.items() if key != "group_id"
    }
    assert result["group_ids"] == [expected["group_id"]]
    if kind in {"pending", "agency"}:
        assert result["default_selected_fields"] == ["zone_name"]
        assert result["default_group_by_field"] == "zone_name"
    if kind == "agency":
        assert "whatsapp:email" in {row["key"] for row in result["agency_match_fields"]}
        assert "whatsapp:email" not in {row["key"] for row in result["fields"]}
    assert "PRIVATE" not in json.dumps(result) and "private@example" not in json.dumps(result)
    assert "expected_revision" not in result
    await no_business_effects(f.session)


@pytest.mark.parametrize("include_empty", [False, True])
async def test_combined_options_match_website_preserving_order_and_complete_union(
    artifacts, include_empty
):
    f = artifacts
    second = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        name="Fixture trip",
        token=uuid.uuid4().hex,
        nearest_international_airport_enabled=True,
        agency_dealership_name_enabled=True,
    )
    empty = ClientGroupModel(
        id=uuid.uuid4(), agency_id=f.agency.id, name="Empty", token=uuid.uuid4().hex
    )
    f.session.add_all([second, empty])
    await f.session.flush()
    await imported_source(f.session, f.group, {"Shared": "PRIVATE-A", "First Only": "PRIVATE-B"})
    await imported_source(
        f.session,
        second,
        {"Zone Name": "PRIVATE-C", "Shared": "PRIVATE-D", "Second Only": "PRIVATE-E"},
    )
    await f.session.commit()
    selected = [second.id, f.group.id] + ([empty.id] if include_empty else [])
    result = await inspect(f, selected, "selected_groups")
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    website = await get_selected_groups_export_fields(
        ExportSelectedGroupsRequest(group_ids=selected),
        current_user=replace(actor, agency_id=f.agency.id),
        session=f.session,
    )
    expected = website.model_dump(mode="json")
    assert {key: result[key] for key in expected} == expected
    assert result["group_ids"] == [str(value) for value in selected]
    assert result["agency_match_supported"] is False and result["agency_match_fields"] == []
    assert result["agency_match_enabled"] is False
    assert {row["key"] for row in result["fields"]} == {
        "zone_name",
        "whatsapp:shared",
        "whatsapp:first_only",
        "whatsapp:second_only",
    }
    await no_business_effects(f.session)


@pytest.mark.parametrize("change", ["wrong_agency", "missing", "one_missing", "deleted"])
async def test_scope_rejects_whole_unavailable_selection(artifacts, change):
    f = artifacts
    groups, agency, selection = [f.group.id], f.agency.id, "group"
    if change == "wrong_agency":
        agency = uuid.uuid4()
    elif change == "missing":
        groups = [uuid.uuid4()]
    elif change == "one_missing":
        groups, selection = [f.group.id, uuid.uuid4()], "selected_groups"
    else:
        f.group.deleted_at = datetime.now(UTC)
        await f.session.commit()
    with pytest.raises(ArtifactError) as failure:
        await MCPExcelOptionsService(f.session, f.settings, excel_options_support()).inspect(
            f.principal,
            ExcelExportOptionsRequest(agency_id=agency, group_ids=groups, selection=selection),
        )
    assert failure.value.status_code == 404
    await no_business_effects(f.session)


@pytest.mark.parametrize("change", ["revoked", "expired", "narrowed", "role"])
async def test_live_authority_is_required_before_catalog_reads(artifacts, change):
    f = artifacts
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    if change == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif change == "expired":
        grant.created_at = datetime.now(UTC) - timedelta(days=2)
        grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "narrowed":
        grant.capabilities = ["mcp:read"]
    else:
        f.user.role = "agency_admin"
    await f.session.commit()
    with pytest.raises(MCPAuthError):
        await inspect(f)


@pytest.mark.parametrize(
    "payload",
    [
        {"group_ids": []},
        {"group_ids": [str(uuid.uuid4())] * 2, "selection": "selected_groups"},
        {"group_ids": [str(uuid.uuid4()) for _ in range(101)], "selection": "selected_groups"},
        {"selection": "selected_passports"},
        {"name": "Ambiguous same-name group"},
        {"agency_match_field": "whatsapp:agency_name"},
        {"mode": "incremental"},
        {"group_ids": [str(uuid.uuid4()), str(uuid.uuid4())]},
    ],
)
def test_input_requires_explicit_coherent_ids_only(payload):
    with pytest.raises(ValidationError):
        ExcelExportOptionsRequest.model_validate(
            {"agency_id": str(uuid.uuid4()), "group_ids": [str(uuid.uuid4())], **payload}
        )


async def http_selection(fixture, fields=None):
    client, session, _, _, _, _ = fixture
    control = await session.get(MCPControlModel, 1)
    control.write_enabled = True
    control.allowed_write_sections = ["exports"]
    control.allowed_write_tools = ["inspect_excel_export_options"]
    await session.commit()
    _, tokens = await connect(
        fixture,
        permissions={
            "write_enabled": True,
            "allowed_write_sections": ["exports"],
        },
    )
    agency = AgencyModel(id=uuid.uuid4(), name="Options fixture", email="options@example.test")
    session.add(agency)
    await session.flush()
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Options",
        token=uuid.uuid4().hex,
        agency_dealership_name_enabled=True,
    )
    session.add(group)
    await session.flush()
    if fields is not None:
        await imported_source(session, group, fields)
    await session.commit()
    return (
        client,
        tokens["access_token"],
        {"selection": {"agency_id": str(agency.id), "group_ids": [str(group.id)]}},
    )


async def test_actual_http_tool_schema_metadata_and_safe_audit_without_business_writes(mcp_fixture):
    client, token, arguments = await http_selection(mcp_fixture, {"Office": "PRIVATE-VALUE"})
    tool = next(
        tool
        for tool in await client._transport.app.state.mcp_server.list_tools()
        if tool.name == "inspect_excel_export_options"
    )
    assert tool.meta == {"capability": "mcp:export"}
    assert tool.annotations.read_only_hint and not tool.annotations.destructive_hint
    result = await call_mcp(client, token, name=tool.name, arguments=arguments)
    assert result.status_code == 200
    payload = result.json()["result"]["structuredContent"]
    assert (
        payload["completeness"] == "complete" and payload["fields"][0]["key"] == "whatsapp:office"
    )
    assert {"audit_id", "revision", "environment", "observed_at"} <= payload.keys()
    assert "expected_revision" not in payload and "PRIVATE" not in json.dumps(payload)
    session = mcp_fixture[1]
    audit = await session.get(AuditLogModel, uuid.UUID(payload["audit_id"]))
    assert audit.result == "success" and audit.metadata_json == {
        "capability": "mcp:export",
        "failure_category": None,
    }
    await no_business_effects(session)


@pytest.mark.parametrize(
    "fields,error",
    [
        (
            {"PRIVATE-" + "界" * 190: "not returned", "Office": "PRIVATE-VALUE"},
            "export_options_unavailable",
        ),
        ({f"Field {index}": "PRIVATE-VALUE" for index in range(257)}, "export_options_limit"),
    ],
)
async def test_http_catalog_failure_is_static_and_never_partial(mcp_fixture, fields, error):
    client, token, arguments = await http_selection(mcp_fixture, fields)
    response = await call_mcp(
        client, token, name="inspect_excel_export_options", arguments=arguments
    )
    payload = response.json()["result"]["structuredContent"]
    assert payload["error"] == error and payload["completeness"] == "unavailable"
    assert (
        "fields" not in payload
        and "PRIVATE" not in json.dumps(payload)
        and "界" not in json.dumps(payload)
    )
    await no_business_effects(mcp_fixture[1])


async def test_actual_http_read_only_grant_cannot_inspect_export_options(mcp_fixture):
    client, _, arguments = await http_selection(mcp_fixture)
    _, tokens = await connect(mcp_fixture, scopes=["mcp:read"])
    response = await call_mcp(
        client, tokens["access_token"], name="inspect_excel_export_options", arguments=arguments
    )
    payload = response.json()["result"]["structuredContent"]
    assert payload["error"] == "access_denied" and "fields" not in payload


async def test_agency_catalog_has_its_own_complete_field_bound(artifacts):
    f = artifacts
    f.group.agency_dealership_name_enabled = True
    await f.session.commit()
    support = excel_options_support()
    fields = [
        {
            "key": f"whatsapp:field_{index}",
            "label": f"Field {index}",
            "source": "whatsapp",
            "selected_by_default": False,
        }
        for index in range(257)
    ]
    support = replace(
        support,
        group=replace(support.group, _export_agency_match_field_catalog=lambda *_args: fields),
    )
    with pytest.raises(ArtifactError, match="field limit") as failure:
        await MCPExcelOptionsService(f.session, f.settings, support).inspect(
            f.principal, ExcelExportOptionsRequest(agency_id=f.agency.id, group_ids=[f.group.id])
        )
    assert failure.value.status_code == 413
    await no_business_effects(f.session)


async def test_options_response_limit_never_returns_partial_projection(artifacts, monkeypatch):
    monkeypatch.setattr(excel_options, "MAX_OPTIONS_BYTES", 1)
    with pytest.raises(ArtifactError, match="response limit"):
        await inspect(artifacts)
    await no_business_effects(artifacts.session)


async def test_full_supplemental_catalog_retains_extra_fixed_airport_grouping(artifacts):
    f = artifacts
    f.group.nearest_international_airport_enabled = True
    await imported_source(
        f.session, f.group, {f"Field {index}": "PRIVATE-VALUE" for index in range(256)}
    )
    await f.session.commit()
    result = await inspect(f)
    assert len(result["fields"]) == result["maximum_fields_per_catalog"] == 256
    assert len(result["grouping_fields"]) == result["maximum_grouping_fields"] == 257
    assert result["grouping_fields"][0] == {
        "key": "international_airport",
        "label": "International Airport",
        "fixed": True,
    }
    assert "PRIVATE" not in json.dumps(result)
    await no_business_effects(f.session)


async def test_projector_preserves_combined_label_collision_resolution(artifacts):
    from app.infrastructure.repositories.client_group_repository import ClientGroupRepository

    f = artifacts
    first = ClientGroupRepository._to_entity(f.group)
    second = replace(first, id=uuid.uuid4())
    support = export_options_support()
    canonical = support.combined_catalog
    # Distinct normalized keys may share a 120-character label after truncation.
    # Canonical merge must disambiguate labels while preserving both full keys.
    from app.application.use_cases.whatsapp.group_submission_matching import RecipientFieldSet
    from tests.unit.presentation.test_selected_groups_export import _pending_match

    label = "A" * 120
    first_row = _pending_match(name="First", phone="+919000000001", zone="North")
    second_row = _pending_match(name="Second", phone="+919000000002", zone="South")
    first_row = replace(
        first_row,
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=uuid.uuid4(), fields={label + "1": "PRIVATE-FIRST", "Zone": "West"}
            ),
        ),
    )
    second_row = replace(
        second_row,
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=uuid.uuid4(),
                fields={label + "2": "PRIVATE-SECOND", "zone name": "East"},
            ),
        ),
    )
    rows = {first.id: [first_row], second.id: [second_row]}
    expected = canonical([first, second], rows, [])
    projection = project_excel_export_options(
        groups=[first, second],
        submissions=[],
        rows_by_group=rows,
        selection="selected_groups",
        support=support,
    )
    assert [item.model_dump() for item in projection.fields] == expected
    assert len({item.label.casefold() for item in projection.fields}) == 3
    assert [item.key for item in projection.fields][0] == "zone_name"
    assert "PRIVATE" not in projection.model_dump_json()
