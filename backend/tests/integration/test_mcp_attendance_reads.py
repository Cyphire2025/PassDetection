"""Canonical attendance SQL/SDK parity and MCP-only bounded read admission."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select

from app.application.mcp import attendance_reads
from app.application.mcp.attendance_reads import AttendanceReadError, MCPAttendanceReadService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.domain.value_objects.attendance_read_limits import (
    AttendanceReadLimits,
)
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceCloseoutCheckpointModel,
    AttendanceRecordModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    AuditLogModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassportExportHistoryModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories import attendance_closeout_repository
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceDashboardRepository,
)
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


def identifier(value):
    return uuid.UUID(f"aaaaaaaa-0000-0000-0000-{value:012x}")


@pytest.fixture
async def attendance_data(mcp_fixture):
    client, session, settings, user, security, dashboard = mcp_fixture
    now = datetime.now(UTC)
    agencies = [
        AgencyModel(id=uuid.uuid4(), name="Attendance", email=f"{uuid.uuid4()}@example.test")
        for _ in range(2)
    ]
    session.add_all(agencies)
    await session.flush()
    user.agency_id = agencies[0].id
    coordinators = [
        UserModel(
            id=uuid.uuid4(),
            agency_id=agencies[0].id,
            email=f"{uuid.uuid4()}@example.test",
            full_name=f"Coordinator {i}",
            hashed_password="unused",
            role="agency_coordinator",
            is_active=True,
        )
        for i in range(2)
    ]
    session.add_all(coordinators)
    groups = [
        ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agencies[int(i == 2)].id,
            name=f"Group {i}",
            token=uuid.uuid4().hex,
            status="active",
            created_by_user_id=user.id,
        )
        for i in range(3)
    ]
    session.add_all(groups)
    await session.flush()
    activity = AttendanceSessionModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        group_id=groups[0].id,
        name="Board bus",
        normalized_name="board bus",
        status="active",
        created_by_user_id=user.id,
        created_at=now - timedelta(hours=1),
        started_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    activity.canonical_session_id = activity.id
    session.add(activity)
    await session.flush()
    alias = AttendanceSessionModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        group_id=groups[0].id,
        canonical_session_id=activity.id,
        name="Legacy bus",
        normalized_name="legacy bus",
        status="active",
        created_by_user_id=user.id,
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    session.add(alias)
    passengers = [
        PassportSubmissionModel(
            id=identifier(i + 1),
            agency_id=agencies[0].id,
            group_id=groups[0].id,
            client_name=("50%_off\\name" if i == 3 else f"Person {i}"),
            client_email="PRIVATE@example.test",
            image_s3_key="PRIVATE-OBJECT",
            status=state,
            extracted_fields={"PRIVATE-JSON": "x" * 20000},
            created_at=now,
            updated_at=now,
        )
        for i, state in enumerate(
            [
                "confirmed",
                "client_submitted",
                "ai_approved",
                "staff_approved",
                "confirmed",
                "confirmed",
                "needs_review",
            ]
        )
    ]
    session.add_all(passengers)
    session.add_all(
        [
            CoordinatorGroupAssignmentModel(
                id=uuid.uuid4(),
                agency_id=agencies[0].id,
                group_id=groups[0].id,
                coordinator_user_id=coordinator.id,
                active=True,
                assigned_at=now - timedelta(hours=2),
            )
            for coordinator in coordinators
        ]
    )
    await session.flush()
    records = []
    for i, (sid, pid, coordinator) in enumerate(
        [
            (activity.id, passengers[0].id, coordinators[0]),
            (alias.id, passengers[0].id, coordinators[1]),
            (alias.id, passengers[1].id, coordinators[1]),
        ]
    ):
        row = AttendanceRecordModel(
            id=uuid.uuid4(),
            agency_id=agencies[0].id,
            session_id=sid,
            passenger_id=pid,
            coordinator_user_id=coordinator.id,
            scanned_at=now + timedelta(seconds=i),
            sync_source="online",
            client_event_id=uuid.uuid4().hex,
            device_id="PRIVATE-DEVICE",
            created_at=now,
        )
        records.append(row)
        session.add(row)
    checkpoint = AttendanceCloseoutCheckpointModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        session_id=activity.id,
        coordinator_user_id=coordinators[0].id,
        pending_count=0,
        sending_count=0,
        retryable_count=0,
        needs_review_count=0,
        unreviewed_rejected_count=0,
        oldest_pending_age_seconds=None,
        reported_at=now,
    )
    session.add(checkpoint)
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
        groups=groups,
        coordinators=coordinators,
        activity=activity,
        alias=alias,
        passengers=passengers,
        records=records,
        checkpoint=checkpoint,
        principal=principal,
        tokens=tokens,
    )


def service(f):
    return MCPAttendanceReadService(f.session, f.settings)


async def revision(f):
    return (await service(f).summary(f.principal, group_id=f.groups[0].id))["sessions"][0][
        "revision"
    ]


async def test_actual_http_summary_missing_pages_and_canonical_alias_parity(attendance_data):
    f = attendance_data
    header = {"Authorization": f"Bearer {f.dashboard}"}
    web = await f.client.get(
        f"/api/v1/tour-operations/groups/{f.groups[0].id}/attendance/summary", headers=header
    )
    assert web.status_code == 200, web.text
    response = await call_mcp(
        f.client,
        f.tokens["access_token"],
        name="get_group_attendance_summary",
        arguments={"group_id": str(f.groups[0].id)},
    )
    result = response.json()["result"]["structuredContent"]
    expected = web.json()

    def normalize(value):
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, str) and "T" in value:
            try:
                return (
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                    .replace(tzinfo=UTC)
                    .isoformat()
                )
            except ValueError:
                pass
        return value

    assert normalize(result["sessions"]) == normalize(expected["sessions"])
    assert (
        result["snapshot_revision"] == expected["revision"]
        and result["revision"] == f.settings.app_revision
    )
    item = result["sessions"][0]
    assert (
        item["present_count"] == 2 and item["missing_count"] == 4 and not item["closeout"]["ready"]
    )
    assert [row["scanned_count"] for row in item["coordinators"]] == [1, 1]
    args = dict(
        group_id=str(f.groups[0].id),
        session_id=str(f.activity.id),
        snapshot_revision=item["revision"],
        page_size=2,
    )
    rows = []
    cursor = None
    while True:
        result = (
            await call_mcp(
                f.client,
                f.tokens["access_token"],
                name="list_missing_attendance_passengers",
                arguments={**args, "cursor": cursor},
            )
        ).json()["result"]["structuredContent"]
        rows += result["items"]
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert [row["passenger_id"] for row in rows] == [str(row.id) for row in f.passengers[2:6]]
    assert "PRIVATE" not in json.dumps(result) and "atomic_snapshot_guaranteed" in json.dumps(
        result
    )
    tools = {
        tool.name: tool for tool in await f.client._transport.app.state.mcp_server.list_tools()
    }
    for name in ("get_group_attendance_summary", "list_missing_attendance_passengers"):
        assert (
            tools[name].meta == {"capability": "mcp:read"}
            and tools[name].annotations.read_only_hint
        )
        assert "agency_id" not in tools[name].input_schema["properties"]
        assert name not in f.client._transport.app.state.mcp_operations
    audit = await f.session.get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.result == "success"


async def test_roster_removal_retains_scans_and_explains_summary_page_divergence(attendance_data):
    f = attendance_data
    f.session.add(
        PassportRosterResolutionModel(
            id=uuid.uuid4(),
            agency_id=f.agencies[0].id,
            client_group_id=f.groups[0].id,
            submission_id=f.passengers[0].id,
            resolution_type="rejected",
            status="active",
            request_id=uuid.uuid4(),
        )
    )
    await f.session.commit()
    result = await service(f).summary(f.principal, group_id=f.groups[0].id)
    activity = result["sessions"][0]
    assert activity["present_count"] == 2 and activity["missing_count"] == 3
    missing = await service(f).missing(
        f.principal,
        group_id=f.groups[0].id,
        session_id=f.activity.id,
        snapshot_revision=activity["revision"],
    )
    assert [row["passenger_id"] for row in missing["items"]] == [
        str(row.id) for row in f.passengers[2:6]
    ]
    assert not missing["has_more"] and len(missing["items"]) != activity["missing_count"]
    assert "not the total number" in result["count_semantics"]["missing_count"]
    assert missing["count_semantics"] == result["count_semantics"]
    assert await f.session.scalar(select(func.count()).select_from(AttendanceRecordModel)) == 3
    web = await f.client.get(
        f"/api/v1/tour-operations/groups/{f.groups[0].id}/attendance/summary",
        headers={"Authorization": f"Bearer {f.dashboard}"},
    )
    assert web.status_code == 200
    assert web.json()["sessions"][0]["present_count"] == 2
    assert web.json()["sessions"][0]["missing_count"] == 3


async def test_search_is_canonical_normalized_and_like_literal(attendance_data):
    f = attendance_data
    snapshot = await revision(f)
    result = await service(f).missing(
        f.principal,
        group_id=f.groups[0].id,
        session_id=f.activity.id,
        snapshot_revision=snapshot,
        search=" 50%_off\\name  ",
    )
    assert [row["passenger_id"] for row in result["items"]] == [str(f.passengers[3].id)]
    assert result["page_size"] == 50 and not result["has_more"]


@pytest.mark.parametrize("stage", ["before", "during"])
async def test_missing_revision_fence_rejects_changes_without_partial_rows(
    attendance_data, monkeypatch, stage
):
    f = attendance_data
    snapshot = await revision(f)

    async def change():
        f.session.add(
            AttendanceRecordModel(
                id=uuid.uuid4(),
                agency_id=f.agencies[0].id,
                session_id=f.activity.id,
                passenger_id=f.passengers[2].id,
                coordinator_user_id=f.coordinators[0].id,
                scanned_at=datetime.now(UTC),
                client_event_id=uuid.uuid4().hex,
                sync_source="online",
            )
        )
        await f.session.flush()

    original = AttendanceDashboardRepository.missing_passengers

    async def during(repo, **kwargs):
        page = await original(repo, **kwargs)
        await change()
        return page

    if stage == "before":
        await change()
    else:
        monkeypatch.setattr(AttendanceDashboardRepository, "missing_passengers", during)
    with pytest.raises(AttendanceReadError, match="attendance_snapshot_changed"):
        await service(f).missing(
            f.principal,
            group_id=f.groups[0].id,
            session_id=f.activity.id,
            snapshot_revision=snapshot,
        )


@pytest.mark.parametrize("binding", ["size", "search", "session", "revision", "signature", "actor"])
async def test_signed_cursor_bindings(attendance_data, binding):
    f = attendance_data
    snapshot = await revision(f)
    args = dict(
        group_id=f.groups[0].id, session_id=f.activity.id, snapshot_revision=snapshot, page_size=1
    )
    first = await service(f).missing(f.principal, **args)
    cursor = first["next_cursor"]
    if binding == "size":
        args["page_size"] = 2
    if binding == "search":
        args["search"] = "Person"
    if binding == "session":
        args["session_id"] = f.alias.id
    if binding == "revision":
        args["snapshot_revision"] = "0" * 32
    if binding == "signature":
        cursor += "x"
    principal = (
        replace(f.principal, user_id=f.coordinators[0].id) if binding == "actor" else f.principal
    )
    error = MCPAuthError if binding == "actor" else AttendanceReadError
    with pytest.raises(error):
        await service(f).missing(principal, **args, cursor=cursor)


@pytest.mark.parametrize(
    "state", ["no_agency", "other_agency", "role", "revoked", "scope", "inactive"]
)
async def test_current_authority_and_own_agency_are_required(attendance_data, state):
    f = attendance_data
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    if state == "no_agency":
        f.user.agency_id = None
    if state == "other_agency":
        f.user.agency_id = f.agencies[1].id
    if state == "role":
        f.user.role = "agency_staff"
    if state == "revoked":
        grant.revoked_at = datetime.now(UTC)
    if state == "scope":
        grant.capabilities = ["mcp:export"]
    if state == "inactive":
        f.user.is_active = False
    await f.session.commit()
    with pytest.raises((MCPAuthError, AttendanceReadError)):
        await service(f).summary(f.principal, group_id=f.groups[0].id)


async def test_empty_group_canonical_unavailable_and_deleted_scope(attendance_data):
    f = attendance_data
    assert (await service(f).summary(f.principal, group_id=f.groups[1].id))["sessions"] == []
    with pytest.raises(AttendanceReadError, match="attendance_activity_unavailable"):
        await service(f).missing(
            f.principal,
            group_id=f.groups[0].id,
            session_id=f.alias.id,
            snapshot_revision=await revision(f),
        )
    f.groups[0].status = "deleted"
    await f.session.commit()
    with pytest.raises(AttendanceReadError, match="attendance_group_unavailable"):
        await service(f).summary(f.principal, group_id=f.groups[0].id)


async def test_projection_uses_only_bounded_scalar_business_reads(attendance_data):
    f = attendance_data
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    def forbid(*_args):
        raise AssertionError("Unexpected business ORM hydration")

    models = (
        ClientGroupModel,
        PassportSubmissionModel,
        AttendanceSessionModel,
        AttendanceCloseoutCheckpointModel,
        AttendanceRuntimeRegistrationModel,
    )
    engine = f.session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    for model in models:
        event.listen(model, "load", forbid)
        event.listen(model, "refresh", forbid)
    try:
        await service(f).summary(f.principal, group_id=f.groups[0].id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        for model in models:
            event.remove(model, "load", forbid)
            event.remove(model, "refresh", forbid)
    sql = " ".join(
        statement
        for statement in statements
        if not any(
            x in statement
            for x in ("from users join", "from users \n", "from user_security_states")
        )
    )
    for forbidden in (
        "runtime_identifier_hash",
        "native_mobile_session_id",
        "client_email",
        "client_phone",
        "extracted_fields",
        "device_id",
        "client_event_id",
        "image_s3_key",
    ):
        assert forbidden not in sql
    assert all(not q.lstrip().startswith(("insert", "update", "delete")) for q in statements)
    for table in (
        "attendance_sessions",
        "attendance_closeout_checkpoints",
        "coordinator_group_assignments",
        "attendance_session_runtime_participants",
    ):
        assert any(table in q and "limit" in q for q in statements)
    for model in (MCPOperationModel, MCPArtifactModel, PassportExportHistoryModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("limit", ["activities", "source_rows", "derived_combinations"])
async def test_limits_reject_before_classification_with_website_default_unchanged(
    attendance_data, monkeypatch, limit
):
    f = attendance_data
    values = dict(activities=100, source_rows=5000, derived_combinations=10000)
    values[limit] = 0
    monkeypatch.setattr(attendance_reads, "READ_LIMITS", AttendanceReadLimits(**values))

    def forbidden(*args, **kwargs):
        raise AssertionError("Classification ran after exceeded admission")

    monkeypatch.setattr(attendance_closeout_repository, "classify_attendance_closeout", forbidden)
    with pytest.raises(AttendanceReadError, match="attendance_read_limit"):
        await service(f).summary(f.principal, group_id=f.groups[0].id)
    assert (
        len(
            (
                await AttendanceDashboardRepository(f.session).group_aggregate(
                    agency_id=f.agencies[0].id, group_id=f.groups[0].id
                )
            ).activities
        )
        == 1
    )


@pytest.mark.parametrize("source", ["group", "activity", "coordinator", "passenger"])
async def test_overlength_text_sentinels_never_return_truncated_content(attendance_data, source):
    f = attendance_data
    snapshot = await revision(f)
    model, field, limit = {
        "group": (f.groups[0], "name", 255),
        "activity": (f.activity, "name", 160),
        "coordinator": (f.coordinators[0], "full_name", 255),
        "passenger": (f.passengers[2], "client_name", 255),
    }[source]
    setattr(model, field, "x" * (limit + 1))
    await f.session.commit()
    with pytest.raises(AttendanceReadError, match="attendance_read_limit"):
        if source == "passenger":
            snapshot = await revision(f)
            await service(f).missing(
                f.principal,
                group_id=f.groups[0].id,
                session_id=f.activity.id,
                snapshot_revision=snapshot,
            )
        else:
            await service(f).summary(f.principal, group_id=f.groups[0].id)


async def test_static_timeout_and_whole_response_budget(attendance_data, monkeypatch):
    f = attendance_data
    monkeypatch.setattr(attendance_reads, "MAX_RESPONSE_BYTES", 256)
    with pytest.raises(AttendanceReadError, match="attendance_read_limit"):
        await service(f).summary(f.principal, group_id=f.groups[0].id)
    monkeypatch.setattr(attendance_reads, "MAX_RESPONSE_BYTES", 512 * 1024)
    monkeypatch.setattr(attendance_reads, "READ_TIMEOUT_SECONDS", 0.2)

    async def stalled(*args, **kwargs):
        await asyncio.sleep(2)

    monkeypatch.setattr(AttendanceDashboardRepository, "group_aggregate", stalled)
    result = (
        await call_mcp(
            f.client,
            f.tokens["access_token"],
            name="get_group_attendance_summary",
            arguments={"group_id": str(f.groups[0].id)},
        )
    ).json()["result"]["structuredContent"]
    assert result["error"] == "attendance_read_busy" and result["completeness"] == "unavailable"
    assert not {"sessions", "items"} & result.keys()


async def test_sdk_summary_marks_coordinator_cap_and_requires_activity_revision(attendance_data):
    f = attendance_data
    for i in range(24):
        user = UserModel(
            id=uuid.uuid4(),
            agency_id=f.agencies[0].id,
            email=f"{uuid.uuid4()}@example.test",
            full_name=f"Extra coordinator {i:02}",
            hashed_password="unused",
            role="agency_coordinator",
            is_active=True,
        )
        f.session.add(user)
        await f.session.flush()
        f.session.add(
            CoordinatorGroupAssignmentModel(
                id=uuid.uuid4(),
                agency_id=f.agencies[0].id,
                group_id=f.groups[0].id,
                coordinator_user_id=user.id,
                assigned_at=datetime.now(UTC) - timedelta(hours=2),
                active=True,
            )
        )
    await f.session.commit()
    result = (
        await call_mcp(
            f.client,
            f.tokens["access_token"],
            name="get_group_attendance_summary",
            arguments={"group_id": str(f.groups[0].id)},
        )
    ).json()["result"]["structuredContent"]
    assert result["completeness"] == "partial"
    activity = result["sessions"][0]
    assert (
        activity["coordinator_count"] == 26
        and activity["coordinators_truncated"]
        and len(activity["coordinators"]) == 25
    )
    assert (
        result["snapshot_revision"] != activity["revision"]
        and result["revision"] == f.settings.app_revision
    )
    args = dict(
        group_id=str(f.groups[0].id),
        session_id=str(f.activity.id),
        snapshot_revision=result["snapshot_revision"],
    )
    wrong = (
        await call_mcp(
            f.client,
            f.tokens["access_token"],
            name="list_missing_attendance_passengers",
            arguments=args,
        )
    ).json()["result"]["structuredContent"]
    assert (
        wrong["error"] == "attendance_snapshot_changed" and wrong["completeness"] == "unavailable"
    )
    args["snapshot_revision"] = activity["revision"]
    correct = (
        await call_mcp(
            f.client,
            f.tokens["access_token"],
            name="list_missing_attendance_passengers",
            arguments=args,
        )
    ).json()["result"]["structuredContent"]
    assert len(correct["items"]) == 4 and correct["snapshot_revision"] == activity["revision"]


@pytest.mark.parametrize(
    "args",
    [
        {"snapshot_revision": "x" * 32},
        {"snapshot_revision": "0" * 32, "page_size": 101},
        {"snapshot_revision": "0" * 32, "search": "x" * 121},
    ],
)
async def test_sdk_input_limits_reject_without_business_results(attendance_data, args):
    f = attendance_data
    response = await call_mcp(
        f.client,
        f.tokens["access_token"],
        name="list_missing_attendance_passengers",
        arguments={"group_id": str(f.groups[0].id), "session_id": str(f.activity.id), **args},
    )
    assert response.json()["result"]["isError"]
