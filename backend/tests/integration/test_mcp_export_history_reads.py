"""Canonical retained history parity, fresh authority and bounded metadata-only reads."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select

from app.application.mcp.artifacts import MCPArtifactService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.export_history_reads import (
    ExportHistoryReadError,
    MCPExportHistoryReadService,
)
from app.application.mcp.exports import MCPExcelExportService
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    PassportExportHistoryModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes.export_history import (
    get_passport_group_export_history_detail,
    list_passport_group_export_history,
)
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.integration.test_mcp_exports import person


@pytest.fixture(autouse=True)
def no_file_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("History discovery cannot render, access storage or create an export")
    monkeypatch.setattr(MCPArtifactService, "storage", property(forbidden))
    monkeypatch.setattr(MCPExcelExportService, "prepare", forbidden)


async def checkpoint(f, *, snapshot=(), exported=None, **overrides):
    exported = list(snapshot) if exported is None else list(exported)
    row = PassportExportHistoryModel(**dict(
        id=uuid.uuid4(), agency_id=f.agency.id, group_id=f.group.id,
        export_kind="passport_excel", export_mode="incremental", format_version=1,
        snapshot_submission_ids=[str(value) for value in snapshot],
        exported_submission_ids=[str(value) for value in exported],
        exported_people_snapshot=[dict(submission_id=str(value), client_name=f"PRIVATE-{i}",
            client_phone="+919999000001", client_email="private@example.test", passport_number="PRIVATE-P")
            for i, value in enumerate(exported)],
        total_available_count=len(snapshot), exported_count=len(exported), pending_recipient_count=4,
        actor_email="private-actor@example.test", created_by_user_id=f.user.id,
        status="completed", created_at=datetime.now(UTC) - timedelta(days=1),
        completed_at=datetime.now(UTC) - timedelta(seconds=1),
        artifact_metadata={"storage_key": "PRIVATE/secret", "filename": "PRIVATE.xlsx"},
    ) | overrides)
    f.session.add(row)
    await f.session.commit()
    return row


async def listing(f, **kwargs):
    return await MCPExportHistoryReadService(f.session, f.settings).list_history(f.principal,
        agency_id=f.agency.id, group_id=f.group.id, kind="passport_excel", **kwargs)


async def detail(f, row, **kwargs):
    return await MCPExportHistoryReadService(f.session, f.settings).get_history(f.principal,
        agency_id=f.agency.id, group_id=f.group.id, history_id=row.id, **kwargs)


async def test_completed_v1_list_matches_website_cumulative_checkpoint_and_live_roster(artifacts):
    f = artifacts
    first, second, new = (person(f, i) for i in range(3))
    f.session.add_all([first, second, new])
    await f.session.flush()
    row = await checkpoint(f, snapshot=[first.id, second.id], exported=[second.id])
    await checkpoint(f, status="prepared", completed_at=None)
    await checkpoint(f, format_version=2)
    await checkpoint(f, export_kind="passport_images")
    result = await listing(f, include_personal_details=True)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    website = await list_passport_group_export_history(f.group.id, export_kind="passport_excel",
        page=1, page_size=25, current_user=replace(actor, agency_id=f.agency.id), session=f.session)
    assert result["items"] == website.model_dump(mode="json")["items"]
    assert result["current_submission_count"] == website.current_submission_count == 3
    assert result["total_count"] == 1 and result["items"][0]["id"] == str(row.id)
    assert result["items"][0]["new_submission_count"] == 1
    assert result["items"][0]["exported_count"] == 1
    assert result["items"][0]["pending_recipient_count"] == 4
    assert result["next_cursor"] is None and result["completeness"] == "complete"
    assert result["maximum_checkpoint_source_bytes"] == f.settings.mcp.export_source_byte_limit
    assert result["maximum_current_roster_ids"] == 5000
    assert result["maximum_response_bytes"] == 512 * 1024


async def test_default_privacy_frozen_order_availability_and_personal_optin_match_website(artifacts):
    f = artifacts
    first = person(f, 1)
    f.session.add(first)
    await f.session.flush()
    missing = uuid.uuid4()
    row = await checkpoint(f, snapshot=[first.id, missing], exported=[missing, first.id])
    first.client_name = "CHANGED-LIVE-NAME"
    await f.session.commit()
    before = json.dumps(row.exported_people_snapshot)
    public = await detail(f, row)
    assert [item["record_available"] for item in public["items"]] == [False, True]
    assert [item["submission_id"] for item in public["items"]] == [str(missing), str(first.id)]
    assert "PRIVATE" not in json.dumps(public) and "private@" not in json.dumps(public)
    assert (await listing(f))["items"][0]["actor_email"] is None
    full = await detail(f, row, include_personal_details=True, page_size=1, page=2)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    website = await get_passport_group_export_history_detail(f.group.id, row.id, page=2, page_size=1,
        current_user=replace(actor, agency_id=f.agency.id), session=f.session)
    assert full["items"] == website.model_dump(mode="json")["items"]
    assert full["items"][0]["client_name"] == "PRIVATE-1"
    assert full["completeness"] == "partial"
    assert json.dumps(row.exported_people_snapshot) == before
    for model in (MCPArtifactModel, MCPOperationModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 0
    audits = (await f.session.scalars(select(AuditLogModel))).all()
    assert any(a.action == "sensitive_read.authorized" for a in audits)
    assert "PRIVATE" not in str([a.metadata_json for a in audits])


@pytest.mark.parametrize("status", ["active", "closed", "archived", "deleted"])
async def test_retained_group_visibility_explicit_optin_and_empty_pending_history(artifacts, status):
    f = artifacts
    f.group.status = status
    if status == "deleted":
        f.group.deleted_at = datetime.now(UTC)
    row = await checkpoint(f, export_kind="passport_images")
    if status == "deleted":
        with pytest.raises(ExportHistoryReadError, match="history_unavailable"):
            await detail(f, row)
    result = await detail(f, row, include_deleted=status == "deleted")
    assert result["items"] == [] and result["pending_recipient_count"] == 4
    assert result["exported_count"] == result["total_pages"] == 0
    assert result["export_kind"] == "passport_images"


@pytest.mark.parametrize("corruption", ["duplicate", "invalid", "count"])
async def test_corrupt_cumulative_checkpoint_is_incompatible_not_false_new_count(artifacts, corruption):
    f = artifacts
    identifier = uuid.uuid4()
    values = [str(identifier), str(identifier)] if corruption == "duplicate" else ["PRIVATE-invalid"] if corruption == "invalid" else []
    row = await checkpoint(f, snapshot_submission_ids=values, total_available_count=2)
    result = await listing(f)
    assert result["items"][0]["compatible"] is False
    assert result["items"][0]["new_submission_count"] == 0
    assert (await detail(f, row))["items"] == []  # detail validates the payload separately


@pytest.mark.parametrize("corruption", ["misordered", "wrong_type", "duplicate"])
async def test_detail_integrity_failures_are_static_and_do_not_expose_partial_rows(artifacts, corruption):
    row = await checkpoint(artifacts, snapshot=[uuid.uuid4(), uuid.uuid4()])
    if corruption == "misordered":
        row.exported_people_snapshot = list(reversed(row.exported_people_snapshot))
    elif corruption == "wrong_type":
        row.exported_people_snapshot = [{**row.exported_people_snapshot[0], "client_name": 7}, row.exported_people_snapshot[1]]
    else:
        row.exported_submission_ids = [row.exported_submission_ids[0]] * 2
    await artifacts.session.commit()
    with pytest.raises(ExportHistoryReadError, match="^history_integrity$"):
        await detail(artifacts, row)


async def test_cursor_binds_actor_filters_and_completion_cutoff_not_preparation_time(artifacts):
    f = artifacts
    rows = [await checkpoint(f) for _ in range(3)]
    first = await listing(f, page_size=1)
    later = await checkpoint(f, completed_at=datetime.now(UTC), created_at=datetime.now(UTC) - timedelta(days=10))
    found = [first["items"][0]["id"]]
    cursor = first["next_cursor"]
    while cursor:
        page = await listing(f, page_size=1, cursor=cursor)
        found.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
    assert set(found) == {str(row.id) for row in rows} and str(later.id) not in found
    for changes in ({"page_size": 2}, {"include_personal_details": True}, {"include_deleted": True}, {"cursor": first["next_cursor"] + "x"}):
        with pytest.raises(ExportHistoryReadError, match="history_invalid_request"):
            await listing(f, **({"page_size": 1, "cursor": first["next_cursor"]} | changes))


@pytest.mark.parametrize("boundary", ["revoked", "expired", "narrowed", "role", "agency", "group", "forged_actor"])
async def test_fresh_authority_precedes_history_access(artifacts, boundary):
    f = artifacts
    row = await checkpoint(f)
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    if boundary == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif boundary == "expired":
        grant.created_at = datetime.now(UTC) - timedelta(days=2)
        grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif boundary == "narrowed":
        grant.capabilities = ["mcp:export"]
    elif boundary == "role":
        f.user.role = "agency_admin"
    await f.session.commit()
    args = dict(agency_id=f.agency.id, group_id=f.group.id, history_id=row.id)
    if boundary in {"agency", "group"}:
        args[boundary + "_id"] = uuid.uuid4()
    principal = replace(f.principal, user_id=uuid.uuid4()) if boundary == "forged_actor" else f.principal
    with pytest.raises((MCPAuthError, ExportHistoryReadError)):
        await MCPExportHistoryReadService(f.session, f.settings).get_history(principal, **args)


async def test_byte_admission_precedes_json_hydration_and_ignores_unused_artifact_data(artifacts):
    f = artifacts
    f.settings.mcp.export_source_byte_limit = 1024 * 1024
    row = await checkpoint(f, snapshot=[uuid.uuid4()])
    row.artifact_metadata = {"ignored": "X" * (2 * 1024 * 1024)}
    await f.session.commit()
    assert len((await listing(f))["items"]) == 1
    row.exported_people_snapshot = [{**row.exported_people_snapshot[0], "client_name": "界" * 400_000}]
    await f.session.commit()
    queries = []
    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)
    engine = f.session.get_bind()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(ExportHistoryReadError, match="history_limit"):
            await detail(f, row)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert not any("passport_export_history.exported_people_snapshot" in query and "sum(" not in query.lower() for query in queries)


async def test_http_tools_have_read_only_scope_static_errors_and_no_generation_gate(mcp_fixture):
    client, session, settings, user, _, _ = mcp_fixture
    _, tokens = await connect(mcp_fixture, scopes=["mcp:read"])
    tools = {tool.name: tool.model_dump(by_alias=True) for tool in await client._transport.app.state.mcp_server.list_tools()}
    for name in ("list_group_export_history", "get_group_export_history"):
        assert tools[name]["annotations"]["readOnlyHint"] is True
        assert tools[name]["_meta"]["capability"] == "mcp:read"
    args = dict(agency_id=str(uuid.uuid4()), group_id=str(uuid.uuid4()), kind="passport_excel")
    response = await call_mcp(client, tokens["access_token"], name="list_group_export_history", arguments=args)
    assert response.json()["result"]["structuredContent"]["completeness"] == "unavailable"
    assert "history_unavailable" in response.text
    assert "SELECT" not in response.text
    _, no_read = await connect(mcp_fixture, scopes=["mcp:export"])
    denied = await call_mcp(client, no_read["access_token"], name="list_group_export_history", arguments=args)
    assert denied.json()["result"]["structuredContent"]["error"] == "access_denied"


async def test_http_success_is_metadata_only_and_current_grant_is_rechecked_between_pages(mcp_fixture):
    client, session, settings, user, _, _ = mcp_fixture
    _, tokens = await connect(mcp_fixture, scopes=["mcp:read"])
    agency = AgencyModel(id=uuid.uuid4(), name="History fixture", email="history@example.test")
    session.add(agency)
    await session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="History", token=uuid.uuid4().hex)
    session.add(group)
    await session.flush()
    fixture = SimpleNamespace(session=session, agency=agency, group=group, user=user)
    one, two = await checkpoint(fixture), await checkpoint(fixture)
    args = dict(agency_id=str(agency.id), group_id=str(group.id), kind="passport_excel", page_size=1)
    response = await call_mcp(client, tokens["access_token"], name="list_group_export_history", arguments=args)
    payload = response.json()["result"]["structuredContent"]
    assert payload["completeness"] == "partial" and payload["has_more"]
    assert {"audit_id", "revision", "environment", "observed_at"} <= payload.keys()
    assert "PRIVATE" not in json.dumps(payload) and "private-actor" not in json.dumps(payload)
    audit = await session.get(AuditLogModel, uuid.UUID(payload["audit_id"]))
    assert audit.result == "success" and audit.metadata_json == {"capability": "mcp:read", "failure_category": None}
    grant = (await session.scalars(select(MCPGrantModel))).one()
    grant.capabilities = ["mcp:export"]
    await session.commit()
    denied = await call_mcp(client, tokens["access_token"], name="list_group_export_history",
        arguments={**args, "cursor": payload["next_cursor"]})
    assert denied.json()["result"]["structuredContent"]["error"] == "access_denied"
    await session.refresh(one)
    await session.refresh(two)
    assert one.status == two.status == "completed"
    for model in (MCPArtifactModel, MCPOperationModel):
        assert await session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("change", [{"status": "prepared", "completed_at": None}, {"format_version": 2}])
async def test_detail_hides_incomplete_and_newer_format_checkpoints(artifacts, change):
    row = await checkpoint(artifacts, **change)
    with pytest.raises(ExportHistoryReadError, match="history_unavailable"):
        await detail(artifacts, row)


async def test_response_bound_rejects_complete_personal_output_without_truncation(artifacts):
    row = await checkpoint(artifacts, snapshot=[uuid.uuid4()])
    row.exported_people_snapshot = [{**row.exported_people_snapshot[0], "client_name": "界" * 90_000}]
    await artifacts.session.commit()
    assert len((await detail(artifacts, row))["items"]) == 1
    with pytest.raises(ExportHistoryReadError, match="history_limit"):
        await detail(artifacts, row, include_personal_details=True)


async def test_cursor_cannot_be_reused_by_another_actor(artifacts):
    from app.application.mcp.read_cursor import MCPReadCursor
    first = await checkpoint(artifacts)
    await checkpoint(artifacts)
    payload = await listing(artifacts, page_size=1)
    cursors = MCPReadCursor(artifacts.settings.app_secret_key, "mcp-export-history-v1")
    with pytest.raises(ValueError):
        cursors.read(payload["next_cursor"], dict(user_id=uuid.uuid4(), agency_id=artifacts.agency.id,
            group_id=artifacts.group.id, kind="passport_excel", page_size=1, personal=False, deleted=False))
    assert first.status == "completed"
