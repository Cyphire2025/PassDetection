"""Bounded current-agency rename metadata parity and harmless read effects."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select, update

from app.application.mcp import rename_reads
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.rename_reads import MCPRenameReadService
from app.application.use_cases.document_rename.read_scope import DocumentRenameScopeError
from app.domain.entities.entities import UserRole
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    DocumentUploadChunkModel,
    UserModel,
)
from app.infrastructure.repositories.document_rename_read_repository import (
    RenameReadLimitError,
    RenameReadUnavailableError,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.document_rename import get_rename_batch, list_rename_batches
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.mcp_rename_fixtures import seed_rename_data


@pytest.fixture
async def rename_data(operations_fixture):
    f = operations_fixture
    data = await seed_rename_data(f[0], f[2])
    f[3][0].capabilities = ["mcp:read", "mcp:change"]
    await f[0].commit()
    return f, data


def reader(f):
    return MCPRenameReadService(f[0], f[1])


def principal(f):
    grant = f[3][0]
    return MCPPrincipal(grant.id, f[2].id, grant.client_id, tuple(grant.capabilities), grant.expires_at, grant.resource)


async def test_list_and_detail_canonical_parity_inactive_agency_and_no_file_authority(rename_data):
    f, data = rename_data
    actor = await UserRepository(f[0]).get_by_id(f[2].id)
    listed = await reader(f).list_batches(principal(f))
    website = await list_rename_batches(actor, f[0])
    assert data.agencies[0].is_active is False  # Existing read scope does not add an agency-active rule.
    assert [row["batch_id"] for row in listed["items"]] == [str(row.batch_id) for row in website]
    for actual, canonical in zip(listed["items"], website, strict=True):
        web = canonical.model_dump(mode="json", exclude={"zip_download_url"})
        web["created_at"] = web["created_at"].replace("Z", "+00:00")
        assert actual == web
    detailed = await reader(f).get_batch(principal(f), data.batches[0].id, include_extracted_identifiers=True)
    canonical = await get_rename_batch(data.batches[0].id, actor, f[0])
    by_id = {str(row.id): row for row in canonical.items}
    assert detailed["total_items"] == 6 and detailed["total_count"] == 99
    for actual in detailed["items"]:
        web = by_id[actual["id"]].model_dump(mode="json")
        assert {key: value for key, value in actual.items() if key != "download_metadata_eligible"} == {
            key: value for key, value in web.items() if key != "download_url"}
        assert actual["download_metadata_eligible"] == bool(web["download_url"])
    assert "DO-NOT-HYDRATE" not in json.dumps(detailed) and "download_url" not in json.dumps(detailed)
    assert detailed["files_accessed"] == 0 and detailed["content_trust"] == "untrusted_business_data"
    for model in (MCPOperationModel, MCPArtifactModel, DocumentUploadChunkModel):
        assert await f[0].scalar(select(func.count()).select_from(model)) == 0


async def test_scalar_projection_omits_keys_and_opt_out_identifier_columns(rename_data):
    f, data = rename_data
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())
    def forbidden(*args):
        raise AssertionError("Rename read hydrated full ORM rows")
    engine = f[0].bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    for model in (DocumentRenameBatchModel, DocumentRenameItemModel):
        event.listen(model, "load", forbidden)
        event.listen(model, "refresh", forbidden)
    try:
        result = await reader(f).get_batch(principal(f), data.batches[0].id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        for model in (DocumentRenameBatchModel, DocumentRenameItemModel):
            event.remove(model, "load", forbidden)
            event.remove(model, "refresh", forbidden)
    assert len(statements) == 9
    item_sql = next(sql for sql in statements if " as storage_present" in sql).split("\nfrom")[0]
    assert "storage_key !=" in item_sql and " as storage_present" in item_sql
    assert " document_rename_items.storage_key," not in item_sql
    assert "document_rename_items.extracted_name" not in item_sql and "substr(" in item_sql
    assert "PRIVATE-EXTRACTED" not in json.dumps(result)
    assert all(row["extracted_name"] is None and row["extracted_passport_number"] is None and row["extracted_reference"] is None for row in result["items"])


async def test_complete_batch_keyset_pagination_beyond_website_window_and_ties(rename_data):
    f, data = rename_data
    stamp = datetime(2026, 9, 10, tzinfo=UTC)
    for index in range(105):
        f[0].add(DocumentRenameBatchModel(id=uuid.UUID(f"aaaaaaaa-0000-0000-0000-{index:012x}"),
            agency_id=data.agencies[0].id, title="Synthetic batch", created_at=stamp))
    await f[0].flush()
    first = await reader(f).list_batches(principal(f))
    rest = await reader(f).list_batches(principal(f), cursor=first["next_cursor"])
    assert len(first["items"]) == 100 and len(rest["items"]) == 8
    assert len({row["batch_id"] for row in first["items"] + rest["items"]}) == 108
    assert first["items"][0]["batch_id"].endswith("000000000068")
    assert rest["next_cursor"] is None
    for kwargs in ({"page_size": 99}, {"cursor": first["next_cursor"] + "x"}):
        with pytest.raises(ValueError):
            await reader(f).list_batches(principal(f), **({"cursor": first["next_cursor"]} | kwargs))
    await f[0].execute(update(UserModel).where(UserModel.id == f[2].id).values(agency_id=data.agencies[1].id))
    with pytest.raises(ValueError):
        await reader(f).list_batches(principal(f), cursor=first["next_cursor"])


async def test_detail_pages_are_filename_then_uuid_and_empty_processing_supported(rename_data):
    f, data = rename_data
    pages = [await reader(f).get_batch(principal(f), data.batches[0].id, page=page, page_size=2) for page in (1, 2, 3)]
    ids = [row["id"] for result in pages for row in result["items"]]
    assert ids == [str(row.id) for row in data.items] and len(set(ids)) == 6
    assert [result["has_more"] for result in pages] == [True, True, False]
    assert all(result["total_pages"] == 3 for result in pages)
    empty = await reader(f).get_batch(principal(f), data.batches[1].id)
    assert empty["status"] == "processing" and empty["total_items"] == 0 and empty["items"] == []


async def test_missing_foreign_batch_and_foreign_item_scope(rename_data):
    f, data = rename_data
    for identifier in (uuid.uuid4(), data.batches[3].id):
        with pytest.raises(RenameReadUnavailableError):
            await reader(f).get_batch(principal(f), identifier)
    await f[0].execute(update(DocumentRenameItemModel).where(DocumentRenameItemModel.id == data.items[0].id)
        .values(agency_id=data.agencies[1].id))
    detail = await reader(f).get_batch(principal(f), data.batches[0].id)
    assert detail["total_items"] == 5 and str(data.items[0].id) not in json.dumps(detail)


async def test_missing_agency_and_shared_website_staff_coordinator_scope(rename_data):
    f, data = rename_data
    staff = await UserRepository(f[0]).get_by_id(data.staff.id)
    website = await list_rename_batches(staff, f[0])
    assert [row.batch_id for row in website] == [data.batches[2].id]
    staff.role = UserRole.AGENCY_COORDINATOR
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as denied:
        await list_rename_batches(staff, f[0])
    assert denied.value.status_code == 403
    await f[0].execute(update(UserModel).where(UserModel.id == f[2].id).values(agency_id=None))
    with pytest.raises(DocumentRenameScopeError):
        await reader(f).list_batches(principal(f))


@pytest.mark.parametrize("field,value", [("title", "x" * 161), ("status", "x" * 33), ("total_count", -1)])
async def test_batch_field_or_counter_limit_fails_without_partial_rows(rename_data, field, value):
    f, data = rename_data
    await f[0].execute(update(DocumentRenameBatchModel).where(DocumentRenameBatchModel.id == data.batches[2].id).values(**{field: value}))
    with pytest.raises(RenameReadLimitError):
        await reader(f).list_batches(principal(f))


@pytest.mark.parametrize("kwargs", [{"page": 0}, {"page": 16}, {"page": True}, {"page_size": 101},
    {"page_size": True}, {"include_extracted_identifiers": 1}])
async def test_detail_input_bounds(rename_data, kwargs):
    f, data = rename_data
    with pytest.raises(ValueError):
        await reader(f).get_batch(principal(f), data.batches[0].id, **kwargs)


async def test_complete_envelope_budget_is_reserved_before_return(rename_data, monkeypatch):
    f, _ = rename_data
    value = await reader(f).list_batches(principal(f))
    service_bytes = len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode())
    monkeypatch.setattr(rename_reads, "MAX_RENAME_RESPONSE_BYTES", service_bytes + 1)
    with pytest.raises(RenameReadLimitError):
        await reader(f).list_batches(principal(f))


async def test_current_grant_rechecked_for_stale_principal_before_projection(rename_data):
    f, _ = rename_data
    saved = principal(f)
    f[3][0].revoked_at = datetime.now(UTC)
    await f[0].commit()
    with pytest.raises(MCPAuthError):
        await reader(f).list_batches(saved)
