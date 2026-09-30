"""Real SQLite/SDK ECR scope, live pagination, scalar budgets and effect proof."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select

from app.application.mcp import ecr_reads
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.ecr_reads import ECRReadError, MCPECRReadService
from app.domain.entities.entities import UserRole
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    PassportExportHistoryModel,
    UserModel,
)
from app.infrastructure.repositories.ecr_read_repository import ECRReadRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import ecr_checker
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


def fixed_id(value):
    return uuid.UUID(f"aaaaaaaa-0000-0000-0000-{value:012x}")


@pytest.fixture
async def ecr_data(mcp_fixture):
    client, session, settings, user, security, dashboard = mcp_fixture
    agencies = [
        AgencyModel(id=uuid.uuid4(), name=name, email=f"{uuid.uuid4()}@example.test")
        for name in ("ECR", "Other")
    ]
    session.add_all(agencies)
    await session.flush()
    user.agency_id = agencies[0].id
    staff = UserModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        email=f"{uuid.uuid4()}@example.test",
        full_name="Staff",
        hashed_password="unused",
        role="agency_staff",
        is_active=True,
    )
    session.add(staff)
    await session.flush()
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    batches = [
        EcrBatchModel(
            id=fixed_id(i + 1),
            agency_id=agencies[int(i == 2)].id,
            created_by_user_id=staff.id if i == 1 else user.id,
            title=f"Batch {i}",
            expected_count=1000,
            status="uploading",
            created_at=stamp,
            lease_token=uuid.uuid4(),
        )
        for i in range(3)
    ]
    session.add_all(batches)
    await session.flush()
    items = []
    for i, (status, result) in enumerate(
        [
            ("queued", None),
            ("processing", None),
            ("completed", "ECR"),
            ("completed", "NA"),
            ("completed", "NEEDS_REVIEW"),
            ("failed", None),
        ]
    ):
        item = EcrItemModel(
            id=fixed_id(100 + i),
            batch_id=batches[0].id,
            client_id=uuid.uuid4(),
            original_filename="duplicate.jpg",
            content_type="image/jpeg",
            object_key="PRIVATE-OBJECT",
            sha256="f" * 64,
            status=status,
            result=result,
            reason="Untrusted business text" if result else None,
            model="PRIVATE-MODEL",
            input_tokens=10,
            output_tokens=5,
            attempts=1,
            created_at=stamp,
        )
        items.append(item)
        session.add(item)
    await session.commit()
    _, tokens = await connect(mcp_fixture)
    principal = await MCPAuthorizationService(session, settings).verify_access(
        tokens["access_token"]
    )
    await session.commit()
    return SimpleNamespace(
        client=client,
        session=session,
        settings=settings,
        user=user,
        security=security,
        dashboard=dashboard,
        agencies=agencies,
        staff=staff,
        batches=batches,
        items=items,
        principal=principal,
        tokens=tokens,
    )


def service(f):
    return MCPECRReadService(f.session, f.settings)


async def test_real_http_sdk_matches_website_and_preserves_no_effects(ecr_data):
    f = ecr_data
    web = await f.client.get(
        "/api/v1/ecr-checker/batches", headers={"Authorization": f"Bearer {f.dashboard}"}
    )
    assert web.status_code == 200, web.text
    response = await call_mcp(
        f.client, f.tokens["access_token"], name="list_ecr_batches", arguments={}
    )
    result = response.json()["result"]["structuredContent"]

    def normalized(row):
        return {key: value for key, value in row.items() if key != "created_at"}

    assert sorted(map(normalized, result["items"]), key=lambda row: row["batch_id"]) == sorted(
        map(normalized, web.json()), key=lambda row: row["batch_id"]
    )
    detail = await call_mcp(
        f.client,
        f.tokens["access_token"],
        name="get_ecr_batch",
        arguments={"batch_id": str(f.batches[0].id)},
    )
    payload = detail.json()["result"]["structuredContent"]
    website = await ecr_checker.get_ecr_batch(
        f.batches[0].id, await UserRepository(f.session).get_by_id(f.user.id), f.session
    )
    assert [normalized(row) for row in payload["items"]] == website.model_dump(mode="json")["items"]
    assert {
        key: payload["batch"][key]
        for key in (
            "total_count",
            "processed_count",
            "ecr_count",
            "na_count",
            "review_count",
            "failed_count",
        )
    } == dict(
        total_count=6, processed_count=4, ecr_count=1, na_count=1, review_count=1, failed_count=1
    )
    assert {"observed_at", "audit_id", "revision", "environment"} <= payload.keys()
    assert payload["consistency"]["snapshot_guaranteed"] is False
    assert "PRIVATE-" not in json.dumps(payload) and "sha256" not in json.dumps(payload)
    app = f.client._transport.app
    tools = {tool.name: tool for tool in await app.state.mcp_server.list_tools()}
    for name in ("list_ecr_batches", "get_ecr_batch"):
        assert (
            tools[name].annotations.read_only_hint and not tools[name].annotations.destructive_hint
        )
        assert (
            tools[name].meta == {"capability": "mcp:read"} and name not in app.state.mcp_operations
        )
        assert "agency_id" not in tools[name].input_schema["properties"]
    audit = await f.session.get(AuditLogModel, uuid.UUID(payload["audit_id"]))
    assert audit.result == "success" and audit.metadata_json == {
        "capability": "mcp:read",
        "failure_category": None,
    }
    for model in (MCPOperationModel, MCPArtifactModel, PassportExportHistoryModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 0


async def test_batches_walk_beyond_latest50_with_ties_and_new_row_cutoff(ecr_data):
    f = ecr_data
    f.session.add_all(
        [
            EcrBatchModel(
                id=fixed_id(1000 + i),
                agency_id=f.agencies[0].id,
                created_by_user_id=f.user.id,
                title="Retained",
                expected_count=1,
                created_at=f.batches[0].created_at,
            )
            for i in range(105)
        ]
    )
    await f.session.commit()
    first = await service(f).list_batches(f.principal, page_size=50)
    newer = EcrBatchModel(
        id=uuid.uuid4(),
        agency_id=f.agencies[0].id,
        title="New",
        expected_count=1,
        created_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    f.session.add(newer)
    await f.session.commit()
    rows = first["items"]
    cursor = first["next_cursor"]
    while cursor:
        page = await service(f).list_batches(f.principal, page_size=50, cursor=cursor)
        rows += page["items"]
        cursor = page["next_cursor"]
    assert len(rows) == 107 and len({row["batch_id"] for row in rows}) == 107
    assert [uuid.UUID(row["batch_id"]).int for row in rows] == sorted(
        [fixed_id(i).int for i in [1, 2, *range(1000, 1105)]], reverse=True
    )
    assert (
        len(
            await ecr_checker.list_ecr_batches(
                await UserRepository(f.session).get_by_id(f.user.id), f.session
            )
        )
        == 50
    )


async def test_item_pages_preserve_duplicates_and_live_counts_with_creation_cutoff(ecr_data):
    f = ecr_data
    first = await service(f).get_batch(f.principal, batch_id=f.batches[0].id, page_size=2)
    f.items[1].status = "completed"
    f.items[1].result = "ECR"
    f.session.add(
        EcrItemModel(
            id=uuid.uuid4(),
            batch_id=f.batches[0].id,
            client_id=uuid.uuid4(),
            original_filename="new.jpg",
            content_type="image/jpeg",
            sha256="0" * 64,
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    await f.session.commit()
    rows = first["items"]
    cursor = first["next_cursor"]
    while cursor:
        page = await service(f).get_batch(
            f.principal, batch_id=f.batches[0].id, page_size=2, cursor=cursor
        )
        assert page["batch"]["total_count"] == 7 and page["batch"]["processed_count"] == 5
        rows += page["items"]
        cursor = page["next_cursor"]
    assert [row["id"] for row in rows] == [str(item.id) for item in f.items]
    assert len({row["original_filename"] for row in rows}) == 1


@pytest.mark.parametrize("mutation", ["size", "signature", "batch", "query", "agency", "expired"])
async def test_cursor_binding_rejects_changes(ecr_data, mutation):
    f = ecr_data
    s = service(f)
    page = await s.get_batch(f.principal, batch_id=f.batches[0].id, page_size=1)
    cursor = page["next_cursor"]
    kwargs = dict(batch_id=f.batches[0].id, page_size=1, cursor=cursor)
    if mutation == "size":
        kwargs["page_size"] = 2
    if mutation == "signature":
        kwargs["cursor"] = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    if mutation == "batch":
        kwargs["batch_id"] = f.batches[1].id
    if mutation == "agency":
        f.user.agency_id = f.agencies[1].id
        await f.session.commit()
        kwargs["batch_id"] = f.batches[2].id
    if mutation == "expired":
        actor = await UserRepository(f.session).get_by_id(f.user.id)
        state, _ = s._state(cursor, actor, 1, f.batches[0].id)
        state["expires"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        kwargs["cursor"] = s.cursors.encode(state)
    with pytest.raises(ECRReadError, match="ecr_read_invalid_request"):
        if mutation == "query":
            await s.list_batches(f.principal, page_size=1, cursor=cursor)
        else:
            await s.get_batch(f.principal, **kwargs)


@pytest.mark.parametrize(
    "change",
    [
        "no_agency",
        "inactive_agency",
        "role",
        "inactive_user",
        "deleted_user",
        "version",
        "revoke",
        "scope",
    ],
)
async def test_current_authority_failure_never_returns_retained_data(ecr_data, change):
    f = ecr_data
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    if change == "no_agency":
        f.user.agency_id = None
    if change == "inactive_agency":
        f.agencies[0].is_active = False
    if change == "role":
        f.user.role = "agency_admin"
    if change == "inactive_user":
        f.user.is_active = False
    if change == "deleted_user":
        f.user.deleted_at = datetime.now(UTC)
    if change == "version":
        f.security.session_version += 1
    if change == "revoke":
        grant.revoked_at = datetime.now(UTC)
    if change == "scope":
        grant.capabilities = ["mcp:export"]
    await f.session.commit()
    with pytest.raises(MCPAuthError):
        await service(f).list_batches(f.principal)


async def test_scope_forgery_cross_agency_and_empty_are_explicit(ecr_data):
    f = ecr_data
    with pytest.raises(ECRReadError, match="ecr_batch_unavailable"):
        await service(f).get_batch(f.principal, batch_id=f.batches[2].id)
    with pytest.raises(MCPAuthError):
        await service(f).list_batches(replace(f.principal, user_id=f.staff.id))
    result = await service(f).get_batch(f.principal, batch_id=f.batches[1].id)
    assert (
        result["items"] == []
        and result["batch"]["total_count"] == 0
        and result["next_cursor"] is None
    )


@pytest.mark.parametrize("role", list(UserRole))
async def test_shared_scope_matches_website_roles_and_staff_ownership(ecr_data, role):
    f = ecr_data
    f.staff.role = role.value
    await f.session.commit()
    actor = await UserRepository(f.session).get_by_id(f.staff.id)
    repo = ECRReadRepository(f.session)
    if role not in {
        UserRole.SUPER_ADMIN,
        UserRole.AGENCY_ADMIN,
        UserRole.AGENCY_MANAGER,
        UserRole.AGENCY_STAFF,
    }:
        with pytest.raises(Exception, match="Insufficient permissions"):
            await repo.batches(actor, size=100, cutoff=datetime.now(UTC), after=None)
        return
    rows = await repo.batches(actor, size=100, cutoff=datetime.now(UTC), after=None)
    web = await ecr_checker.list_ecr_batches(actor, f.session)
    assert {row["batch_id"] for row in rows} == {row.batch_id for row in web}
    assert len(rows) == (1 if role == UserRole.AGENCY_STAFF else 2)


async def test_scalar_queries_bounded_and_no_business_orm_or_writes(ecr_data):
    f = ecr_data
    statements = []

    def capture(_conn, _cursor, statement, *args):
        statements.append(statement.lower())

    def forbid(*args):
        raise AssertionError("Unexpected ECR ORM materialization")

    engine = f.session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    for model in (EcrBatchModel, EcrItemModel):
        event.listen(model, "load", forbid)
        event.listen(model, "refresh", forbid)
    try:
        await service(f).get_batch(f.principal, batch_id=f.batches[0].id, page_size=2)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        for model in (EcrBatchModel, EcrItemModel):
            event.remove(model, "load", forbid)
            event.remove(model, "refresh", forbid)
    assert len(statements) <= 9
    assert all(
        not statement.lstrip().startswith(("insert", "update", "delete"))
        for statement in statements
    )
    business = " ".join(statement for statement in statements if "ecr_" in statement)
    for field in (
        "object_key",
        "sha256",
        "lease_token",
        "lease_expires_at",
        "input_tokens",
        "output_tokens",
        "ecr_items.model",
    ):
        assert field not in business
    assert "limit" in business and "substr" in business and "count(" in business


@pytest.mark.parametrize(
    "field,length", [("title", 161), ("original_filename", 256), ("reason", 256)]
)
async def test_oversized_retained_text_is_rejected_not_truncated(ecr_data, field, length):
    f = ecr_data
    setattr(f.batches[0] if field == "title" else f.items[2], field, "x" * length)
    await f.session.commit()
    with pytest.raises(ECRReadError, match="ecr_read_limit"):
        await service(f).get_batch(f.principal, batch_id=f.batches[0].id)


async def test_utf8_response_budget_and_deadline_are_static_safe_errors(ecr_data, monkeypatch):
    f = ecr_data
    monkeypatch.setattr(ecr_reads, "MAX_RESPONSE_BYTES", 128)
    with pytest.raises(ECRReadError, match="ecr_read_limit"):
        await service(f).list_batches(f.principal)
    monkeypatch.setattr(ecr_reads, "MAX_RESPONSE_BYTES", 256 * 1024)
    monkeypatch.setattr(ecr_reads, "READ_TIMEOUT_SECONDS", 0.2)

    async def stalled(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(ECRReadRepository, "batches", stalled)
    response = await call_mcp(
        f.client, f.tokens["access_token"], name="list_ecr_batches", arguments={}
    )
    result = response.json()["result"]["structuredContent"]
    assert result["error"] == "ecr_read_busy" and result["completeness"] == "unavailable"
    assert "Traceback" not in json.dumps(result)


@pytest.mark.parametrize("page_size", [0, 101, True, 1.1])
async def test_invalid_page_size(ecr_data, page_size):
    with pytest.raises(ECRReadError, match="ecr_read_invalid_request"):
        await service(ecr_data).list_batches(ecr_data.principal, page_size=page_size)


async def test_full_unicode_response_exceeds_real_budget_then_smaller_page_succeeds(ecr_data):
    f = ecr_data
    f.session.add_all(
        [
            EcrItemModel(
                id=uuid.uuid4(),
                batch_id=f.batches[1].id,
                client_id=uuid.uuid4(),
                original_filename="😀" * 255,
                reason="😀" * 255,
                status="completed",
                result="ECR",
                content_type="image/jpeg",
                sha256="0" * 64,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for _ in range(100)
        ]
    )
    await f.session.commit()
    with pytest.raises(ECRReadError, match="ecr_read_limit"):
        await service(f).get_batch(f.principal, batch_id=f.batches[1].id, page_size=100)
    result = await service(f).get_batch(f.principal, batch_id=f.batches[1].id, page_size=20)
    assert (
        result["has_more"] and len(result["items"]) == 20 and result["batch"]["total_count"] == 100
    )
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= 256 * 1024
    assert all(
        row["original_filename"] == "😀" * 255 and row["reason"] == "😀" * 255
        for row in result["items"]
    )


@pytest.mark.parametrize(
    "name,args",
    [("list_ecr_batches", {"page_size": 101}), ("get_ecr_batch", {"batch_id": "invalid"})],
)
async def test_actual_sdk_rejects_invalid_input_before_business_query(ecr_data, name, args):
    f = ecr_data
    response = await call_mcp(f.client, f.tokens["access_token"], name=name, arguments=args)
    assert response.json()["result"]["isError"]
    audit = (
        (
            await f.session.execute(
                select(AuditLogModel).where(AuditLogModel.action == "mcp.tool.invalid_request")
            )
        )
        .scalars()
        .one()
    )
    assert audit.result == "denied" and audit.metadata_json == {
        "reason": "unsupported_or_invalid_tool_request"
    }


async def test_actual_http_missing_scope_and_current_agency_denial(ecr_data):
    f = ecr_data
    f.user.agency_id = None
    await f.session.commit()
    response = await call_mcp(
        f.client, f.tokens["access_token"], name="list_ecr_batches", arguments={}
    )
    result = response.json()["result"]["structuredContent"]
    assert result["error"] == "access_denied" and result["completeness"] == "unavailable"
    assert not {"items", "agency_id", "batch"} & result.keys()
