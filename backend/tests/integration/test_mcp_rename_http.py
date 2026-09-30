"""Actual OAuth/SDK metadata reads, current authority and fixed safe failures."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update

from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
)
from app.infrastructure.repositories.document_rename_read_repository import (
    DocumentRenameReadRepository,
)
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.mcp_rename_fixtures import seed_rename_data


@pytest.fixture
async def rename_data(mcp_fixture):
    data = await seed_rename_data(mcp_fixture[1], mcp_fixture[3])
    await mcp_fixture[1].commit()
    return mcp_fixture, data


def body(response):
    assert response.status_code == 200, response.text
    return response.json()["result"]["structuredContent"]


async def test_oauth_list_and_paged_detail_identifier_optin_no_file_actions(rename_data):
    f, data = rename_data
    _, tokens = await connect(f, scopes=["mcp:read"])
    listed = body(await call_mcp(f[0], tokens["access_token"], name="list_document_rename_batches", arguments={"page_size": 1}))
    assert len(listed["items"]) == 1 and listed["has_more"]
    args = {"batch_id": str(data.batches[0].id), "page": 1, "page_size": 3, "include_extracted_identifiers": False}
    detail = body(await call_mcp(f[0], tokens["access_token"], name="get_document_rename_batch", arguments=args))
    assert len(detail["items"]) == 3 and detail["has_more"] and detail["total_items"] == 6
    assert "PRIVATE-EXTRACTED" not in json.dumps(detail)
    included = body(await call_mcp(f[0], tokens["access_token"], name="get_document_rename_batch",
        arguments={**args, "include_extracted_identifiers": True}))
    assert included["items"][0]["extracted_name"] == "PRIVATE-EXTRACTED-NAME"
    assert {"environment", "revision", "audit_id", "observed_at"} <= detail.keys()
    assert "DO-NOT-HYDRATE" not in json.dumps([listed, detail, included])
    assert await f[1].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    audits = (await f[1].scalars(select(AuditLogModel).where(AuditLogModel.action == "document_rename.mcp_identifiers_read"))).all()
    assert len(audits) == 1
    assert audits[0].entity_id == args["batch_id"]
    assert set(audits[0].metadata_json) == {"mcp_grant_id", "returned_item_count", "page", "page_size", "extracted_identifiers_included"}
    assert audits[0].metadata_json["returned_item_count"] == 3
    assert "PRIVATE" not in json.dumps(audits[0].metadata_json) and "person" not in json.dumps(audits[0].metadata_json)


@pytest.mark.parametrize("target", ["foreign", "missing", "no_agency"])
async def test_unavailable_scope_or_batch_returns_no_metadata(rename_data, target):
    f, data = rename_data
    identifier = data.batches[3].id if target == "foreign" else uuid.uuid4()
    _, tokens = await connect(f, scopes=["mcp:read"])
    if target == "no_agency":
        f[3].agency_id = None
        await f[1].commit()
    result = body(await call_mcp(f[0], tokens["access_token"], name="get_document_rename_batch", arguments={"batch_id": str(identifier)}))
    assert result["error"] == ("rename_scope_unavailable" if target == "no_agency" else "rename_batch_unavailable")
    assert result["completeness"] == "unavailable" and "items" not in result


async def test_field_limit_is_static_audited_and_no_partial_page(rename_data):
    f, data = rename_data
    _, tokens = await connect(f, scopes=["mcp:read"])
    await f[1].execute(update(DocumentRenameItemModel).where(DocumentRenameItemModel.id == data.items[0].id)
        .values(reason="SECRET-OVERSIZE" * 100))
    await f[1].commit()
    result = body(await call_mcp(f[0], tokens["access_token"], name="get_document_rename_batch",
        arguments={"batch_id": str(data.batches[0].id)}))
    assert result["error"] == "rename_read_limit" and result["completeness"] == "unavailable"
    assert "items" not in result and "SECRET" not in json.dumps(result)
    audit = await f[1].get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.result == "blocked"


async def test_signed_cursor_cannot_cross_current_agency(rename_data):
    f, data = rename_data
    _, tokens = await connect(f, scopes=["mcp:read"])
    first = body(await call_mcp(f[0], tokens["access_token"], name="list_document_rename_batches", arguments={"page_size": 1}))
    f[3].agency_id = data.agencies[1].id
    await f[1].commit()
    result = body(await call_mcp(f[0], tokens["access_token"], name="list_document_rename_batches",
        arguments={"page_size": 1, "cursor": first["next_cursor"]}))
    assert result["error"] == "invalid_rename_query" and "items" not in result


@pytest.mark.parametrize("restriction", ["revoked", "capability", "deployment", "role", "inactive", "deleted", "session", "control"])
async def test_current_authority_precedes_business_projection(rename_data, monkeypatch, restriction):
    f, _ = rename_data
    _, tokens = await connect(f, scopes=["mcp:read"])
    grant = await f[1].scalar(select(MCPGrantModel))
    if restriction == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif restriction == "capability":
        grant.capabilities = ["mcp:export"]
    elif restriction == "deployment":
        f[2].mcp.enabled_capabilities = ["mcp:export"]
    elif restriction == "role":
        f[3].role = "agency_staff"
    elif restriction == "inactive":
        f[3].is_active = False
    elif restriction == "deleted":
        f[3].deleted_at = datetime.now(UTC)
    elif restriction == "session":
        f[4].session_version += 1
    else:
        (await f[1].get(MCPControlModel, 1)).enabled = False
    await f[1].commit()
    async def forbidden(*args, **kwargs):
        raise AssertionError("Unauthorized rename source read")
    monkeypatch.setattr(DocumentRenameReadRepository, "batches", forbidden)
    response = await call_mcp(f[0], tokens["access_token"], name="list_document_rename_batches")
    if response.status_code != 401:
        assert body(response)["completeness"] == "unavailable"
    assert await f[1].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_batch_revalidation_rejects_scope_change_without_returning_item_values(rename_data, monkeypatch):
    f, data = rename_data
    identifier, other = data.batches[0].id, data.agencies[1].id
    _, tokens = await connect(f, scopes=["mcp:read"])
    original = DocumentRenameReadRepository.items
    async def moved(repo, *args, **kwargs):
        result = await original(repo, *args, **kwargs)
        await repo.session.execute(update(DocumentRenameBatchModel).where(DocumentRenameBatchModel.id == identifier).values(agency_id=other))
        return result
    monkeypatch.setattr(DocumentRenameReadRepository, "items", moved)
    result = body(await call_mcp(f[0], tokens["access_token"], name="get_document_rename_batch", arguments={"batch_id": str(identifier)}))
    assert result["error"] == "rename_batch_unavailable" and "items" not in result
    assert "Original person" not in json.dumps(result)
