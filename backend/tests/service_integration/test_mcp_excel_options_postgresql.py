"""Retained PostgreSQL options qualification; no workload or capacity claim.

Reuse the UUID-owned 5,000/100 fixture schema and add synthetic empty/import-only
groups. Only options are read: no workbook, history, object or provider operation.
All committed fixtures remain; temporary oversized source changes roll back.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import Text, cast, event, func, insert, select, update

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.excel_options import ExcelExportOptionsRequest, MCPExcelOptionsService
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes.excel_exports import (
    get_passport_group_export_fields,
)
from app.presentation.api.v1.routes.passport_routes.selected_exports import (
    get_selected_groups_export_fields,
)
from app.presentation.api.v1.schemas.passport_schemas import ExportSelectedGroupsRequest
from app.presentation.mcp.excel_options_tools import excel_options_support
from tests.service_integration.test_mcp_source_admission_postgresql import (
    BYTES,
    ROWS,
)
from tests.service_integration.test_mcp_source_admission_postgresql import (
    retained_cohorts as retained_cohorts,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


@pytest.fixture(autouse=True)
def forbid_generation_and_storage(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Options must not render a workbook or initialize object storage")
    monkeypatch.setattr(MCPArtifactService, "storage", property(forbidden))
    monkeypatch.setattr(PassportExcelExporter, "export_group", forbidden)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def options_sources(retained_cohorts):
    f = retained_cohorts
    async with f.sessions() as session:
        empty = ClientGroupModel(id=uuid.uuid4(), agency_id=f.agency_id, name="Empty options",
                                 token=uuid.uuid4().hex, nearest_international_airport_enabled=True)
        imported = ClientGroupModel(id=uuid.uuid4(), agency_id=f.agency_id, name="Imported options",
                                    token=uuid.uuid4().hex, import_only=True)
        broadcast = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=f.agency_id,
            name="Imported options source", imported_field_keys=["Office", "Zone"])
        session.add_all([empty, imported, broadcast])
        await session.flush()
        link = ClientGroupWhatsAppBroadcastLinkModel(id=uuid.uuid4(), agency_id=f.agency_id,
            client_group_id=imported.id, broadcast_group_id=broadcast.id)
        session.add(link)
        recipients = [uuid.uuid4() for _ in range(ROWS)]
        await session.execute(insert(WhatsAppBroadcastRecipientModel), [
            {"id": identifier, "agency_id": f.agency_id, "broadcast_group_id": broadcast.id,
             "name": f"Synthetic recipient {index}", "phone_number": f"+919888{index:06}",
             "normalized_phone_number": f"+919888{index:06}",
             "imported_fields": {"Office": "PRIVATE-CATALOG-VALUE", "Zone": "West"}}
            for index, identifier in enumerate(recipients)
        ])
        await session.commit()
    return SimpleNamespace(base=f, groups={**f.groups, "empty": empty.id, "imported": imported.id},
                           broadcast_id=broadcast.id, recipient_ids=recipients)


def request_for(f, *groups):
    return ExcelExportOptionsRequest(agency_id=f.base.agency_id,
        group_ids=[f.groups[name] for name in groups],
        selection="group" if len(groups) == 1 else "selected_groups")


async def inspect(f, session, request):
    principal = await MCPAuthorizationService(session, f.base.settings).verify_access(f.base.token)
    return await MCPExcelOptionsService(session, f.base.settings, excel_options_support()).inspect(principal, request)


@contextmanager
def forbid_orm(model):
    def forbidden(*_args):
        raise AssertionError("Rejected options source reached full ORM loading")
    event.listen(model, "load", forbidden)
    event.listen(model, "refresh", forbidden)
    try:
        yield
    finally:
        event.remove(model, "load", forbidden)
        event.remove(model, "refresh", forbidden)


@pytest.mark.parametrize("groups", [("small",), ("empty",), ("imported",),
                                     ("imported", "empty"), ("empty", "small")])
async def test_options_match_canonical_website_for_exact_groups(options_sources, groups):
    f, loaded = options_sources, set()
    def record(row, _context):
        loaded.add(row.id)
    async with f.base.sessions() as session:
        event.listen(PassportSubmissionModel, "load", record)
        try:
            actual = await inspect(f, session, request_for(f, *groups))
        finally:
            event.remove(PassportSubmissionModel, "load", record)
        assert loaded == (set(f.base.identifiers["small"]) if "small" in groups else set())
        actor = replace(await UserRepository(session).get_by_id(f.base.user_id), agency_id=f.base.agency_id)
        ids = [f.groups[name] for name in groups]
        if len(ids) == 1:
            response = await get_passport_group_export_fields(ids[0], current_user=actor, session=session)
        else:
            response = await get_selected_groups_export_fields(
                ExportSelectedGroupsRequest(group_ids=ids), current_user=actor, session=session)
        expected = response.model_dump(mode="json")
        for key in ("fields", "grouping_fields", "default_selected_fields", "default_group_by_field"):
            assert actual[key] == expected[key]
        if len(ids) == 1:
            assert actual["agency_match_fields"] == expected["agency_match_fields"]
            assert actual["agency_match_enabled"] == expected["agency_match_enabled"]
        assert actual["group_ids"] == [str(identifier) for identifier in ids]
        assert actual["maximum_source_rows_per_family"] == ROWS
        assert actual["maximum_source_bytes"] == BYTES
        assert actual["completeness"] == "complete"
        assert "expected_revision" not in actual
        assert "PRIVATE-CATALOG-VALUE" not in json.dumps(actual)
        assert f.base.settings.mcp.export_source_row_limit == ROWS
        assert f.base.settings.mcp.export_source_byte_limit == BYTES


@pytest.mark.parametrize("family", ["passports", "recipients"])
async def test_101_rows_rejected_before_family_orm(options_sources, family):
    f = options_sources
    async with f.base.sessions() as session:
        if family == "passports":
            # The existing 5,000-row cohort is retained. Two explicit groups
            # with a combined101 demonstrate admission spans group boundaries.
            await session.execute(insert(PassportSubmissionModel), [{
                "id": uuid.uuid4(), "agency_id": f.base.agency_id, "group_id": f.groups["empty"],
                "client_name": "Transient101", "image_s3_key": "private/never-read",
                "status": "staff_approved", "confirmed_fields": {}}])
            model, request = PassportSubmissionModel, request_for(f, "small", "empty")
        else:
            await session.execute(insert(WhatsAppBroadcastRecipientModel), [{
                "id": uuid.uuid4(), "agency_id": f.base.agency_id, "broadcast_group_id": f.broadcast_id,
                "phone_number": "+919777777777", "normalized_phone_number": "+919777777777",
                "imported_fields": {}}])
            model, request = WhatsAppBroadcastRecipientModel, request_for(f, "imported")
        with forbid_orm(model), pytest.raises(ArtifactError, match="configured row limit") as denied:
            await inspect(f, session, request)
        assert denied.value.status_code == 413
        await session.rollback()


async def test_whole_retained_5000_group_rejected_before_orm(options_sources):
    f = options_sources
    async with f.base.sessions() as session:
        with forbid_orm(PassportSubmissionModel), pytest.raises(ArtifactError, match="configured row limit") as denied:
            await inspect(f, session, request_for(f, "large"))
        assert denied.value.status_code == 413


@pytest.mark.parametrize("family", ["group", "broadcast", "recipient", "passport"])
async def test_utf8_byte_admission_before_full_source_family(options_sources, family):
    f = options_sources
    async with f.base.sessions() as session:
        if family == "group":
            model, column, ids, groups = ClientGroupModel, ClientGroupModel.upload_configuration, [f.groups["empty"]], ("empty",)
        elif family == "broadcast":
            model, column, ids, groups = WhatsAppBroadcastGroupModel, WhatsAppBroadcastGroupModel.imported_field_keys, [f.broadcast_id], ("imported",)
        elif family == "recipient":
            model, column, ids, groups = WhatsAppBroadcastRecipientModel, WhatsAppBroadcastRecipientModel.imported_fields, f.recipient_ids[:2], ("imported",)
        else:
            model, column, ids, groups = PassportSubmissionModel, PassportSubmissionModel.confirmed_fields, f.base.identifiers["small"][:2], ("small",)
        content = "旅" * (350000 if len(ids) == 1 else 180000)
        payload = [content] if family == "broadcast" else {"oversized": content}
        await session.execute(update(model).where(model.id.in_(ids)).values({column.key: payload}))
        value = cast(column, Text)
        sizes = (await session.execute(select(func.sum(func.octet_length(value)), func.sum(func.char_length(value)))
                                       .where(model.id.in_(ids)))).one()
        assert sizes[0] > BYTES > sizes[1]
        with forbid_orm(model), pytest.raises(ArtifactError, match="configured byte limit") as denied:
            await inspect(f, session, request_for(f, *groups))
        assert denied.value.status_code == 413
        await session.rollback()


async def test_recipient_lock_fails_fast_then_retries_fresh_source(options_sources):
    f = options_sources
    request = request_for(f, "imported")
    async with f.base.sessions() as blocker:
        await blocker.scalar(select(WhatsAppBroadcastRecipientModel.id)
            .where(WhatsAppBroadcastRecipientModel.id == f.recipient_ids[0]).with_for_update())
        async with f.base.sessions() as contender:
            with pytest.raises(ArtifactError) as denied:
                await asyncio.wait_for(inspect(f, contender, request), timeout=3)
            assert denied.value.status_code == 503 and "busy" in str(denied.value).lower()
            await contender.rollback()
        await blocker.execute(update(WhatsAppBroadcastRecipientModel)
            .where(WhatsAppBroadcastRecipientModel.id == f.recipient_ids[0])
            .values(imported_fields={"Office": "PRIVATE-CATALOG-VALUE", "Retry field": "PRIVATE-RETRY-VALUE"}))
        await blocker.commit()
    async with f.base.sessions() as session:
        result = await inspect(f, session, request)
        assert any(field["label"] == "Retry field" for field in result["fields"])
        assert "PRIVATE-RETRY-VALUE" not in json.dumps(result)
        assert "expected_revision" not in result
        # Options are an inspection, not a saved generation operation. The
        # caller can inspect again; generation obtains its own source revision.


async def test_options_leave_no_generation_or_message_receipts(options_sources):
    f = options_sources
    async with f.base.sessions() as session:
        await inspect(f, session, request_for(f, "imported", "small"))
        for model in (MCPOperationModel, MCPArtifactModel, PassportExportHistoryModel, WhatsAppMessageLogModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert await session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 5100
        assert await session.scalar(select(func.count()).select_from(WhatsAppBroadcastRecipientModel)) == 100
