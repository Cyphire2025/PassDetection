"""Existing QR images and recorded scans are observations, never new credentials/events."""

from __future__ import annotations

import base64
import io
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from PIL import Image
from sqlalchemy import func, select

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.tour_evidence_reads import MCPTourEvidenceReadService
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceCloseoutCheckpointModel,
    AttendanceRecordModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    AuditLogModel,
    ClientGroupModel,
    PassengerQRTokenModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
)
from app.infrastructure.qr.qr_image_renderer import render_attendance_qr_png
from app.presentation.mcp.tour_evidence_tools import qr_image_result, register_tour_evidence_tools
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def evidence(operations_fixture):
    session, settings, actor, grants, tokens = operations_fixture
    now = datetime.now(UTC)
    control = await session.get(MCPControlModel, 1)
    control.allowed_read_sections = ["tour_ops", "all_groups"]
    for grant in grants:
        grant.capabilities = ["mcp:read"]
    agencies = [
        AgencyModel(id=uuid.uuid4(), name="Evidence agency", email=f"evidence-{i}@example.test")
        for i in range(2)
    ]
    session.add_all(agencies)
    await session.flush()
    actor.agency_id = agencies[0].id
    groups = [
        ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Evidence trip",
            token=uuid.uuid4().hex,
            status="active",
            import_only=True,
        )
        for agency in agencies
    ]
    session.add_all(groups)
    await session.flush()
    passengers = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agencies[0].id,
            group_id=groups[0].id,
            client_name=f"Person {i}",
            client_email="PRIVATE_EMAIL",
            status="confirmed",
            image_s3_key="PRIVATE_OBJECT",
            extracted_fields={"PRIVATE_JSON": "withheld"},
        )
        for i in range(2)
    ]
    session.add_all(passengers)
    await session.flush()
    qr = PassengerQRTokenModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        passenger_id=passengers[0].id,
        token_hash="b" * 64,
        qr_payload="pdatt:" + "safe-existing-fixture" * 2,
        token_version=1,
        is_active=True,
        expires_at=now + timedelta(days=1),
    )
    activity = AttendanceSessionModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        group_id=groups[0].id,
        name="Current activity",
        normalized_name="current activity",
        status="active",
        created_by_user_id=actor.id,
    )
    activity.canonical_session_id = activity.id
    session.add_all([qr, activity])
    await session.flush()
    alias = AttendanceSessionModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        group_id=groups[0].id,
        name="Retained alias",
        normalized_name="retained alias",
        canonical_session_id=activity.id,
        status="active",
        created_by_user_id=actor.id,
    )
    session.add(alias)
    await session.flush()
    records = [
        AttendanceRecordModel(
            id=uuid.uuid4(),
            agency_id=agencies[0].id,
            session_id=(activity.id if i < 2 else alias.id),
            passenger_id=passengers[i % 2].id,
            coordinator_user_id=actor.id,
            scanned_at=now - timedelta(minutes=3 - i),
            created_at=now - timedelta(minutes=3 - i),
            sync_source="online" if i < 2 else "offline",
            client_event_id=uuid.uuid4().hex,
            device_id="PRIVATE_DEVICE",
        )
        for i in range(3)
    ]
    session.add_all(records)
    await session.flush()
    principal = MCPPrincipal(
        grants[0].id,
        actor.id,
        grants[0].client_id,
        ("mcp:read",),
        grants[0].expires_at,
        grants[0].resource,
    )
    return SimpleNamespace(
        session=session,
        settings=settings,
        actor=actor,
        grants=grants,
        tokens=tokens,
        agencies=agencies,
        groups=groups,
        passengers=passengers,
        qr=qr,
        activity=activity,
        alias=alias,
        records=records,
        principal=principal,
    )


def qr_arguments(fixture):
    return dict(
        agency_id=fixture.agencies[0].id,
        group_id=fixture.groups[0].id,
        passenger_id=fixture.passengers[0].id,
    )


def attendance_arguments(fixture):
    return dict(
        agency_id=fixture.agencies[0].id,
        group_id=fixture.groups[0].id,
        activity_id=fixture.activity.id,
    )


def service(fixture):
    return MCPTourEvidenceReadService(fixture.session, fixture.settings)


async def counts(fixture):
    return [
        await fixture.session.scalar(select(func.count()).select_from(model))
        for model in (
            PassengerQRTokenModel,
            AttendanceRecordModel,
            AttendanceSessionModel,
            AttendanceRuntimeRegistrationModel,
            AttendanceCloseoutCheckpointModel,
        )
    ]


@pytest.mark.parametrize("active", [True, False])
async def test_existing_qr_is_actual_canonical_png_without_issuance_or_text_credential(
    evidence, active
):
    f = evidence
    f.qr.is_active = active
    await f.session.flush()
    original_counts, payload = await counts(f), f.qr.qr_payload
    result = await service(f).qr(f.principal, **qr_arguments(f))
    native = qr_image_result(result)
    assert native.is_error is False and len(native.content) == 2
    assert native.content[1].type == "image" and native.content[1].mime_type == "image/png"
    png = base64.b64decode(native.content[1].data, validate=True)
    assert png == render_attendance_qr_png(payload)
    with Image.open(io.BytesIO(png)) as image:
        assert image.format == "PNG" and image.width == image.height and image.width > 100
    text = native.content[0].text
    assert payload not in text and "qr_image_png" not in text and "PRIVATE" not in text
    assert json.loads(text)["qr_status"] == ("active" if active else "inactive")
    assert json.loads(text)["credential_created"] is False
    assert await counts(f) == original_counts


@pytest.mark.parametrize("state", ["revoked", "expired", "not_generated"])
async def test_nonusable_existing_qr_metadata_never_returns_image(evidence, state):
    f = evidence
    if state == "revoked":
        f.qr.revoked_at = datetime.now(UTC)
    elif state == "expired":
        f.qr.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        arguments = {**qr_arguments(f), "passenger_id": f.passengers[1].id}
    await f.session.flush()
    before = await counts(f)
    result = await service(f).qr(
        f.principal, **(arguments if state == "not_generated" else qr_arguments(f))
    )
    native = qr_image_result(result)
    assert len(native.content) == 1 and json.loads(native.content[0].text)["qr_status"] == state
    assert await counts(f) == before


@pytest.mark.parametrize(
    "change",
    [
        "foreign_agency",
        "foreign_group",
        "foreign_actor",
        "nonapproved",
        "removed_passenger",
        "deleted_group",
    ],
)
async def test_qr_scope_and_operational_roster_are_current(evidence, change):
    f = evidence
    arguments = qr_arguments(f)
    if change == "foreign_agency":
        arguments["agency_id"] = f.agencies[1].id
    elif change == "foreign_group":
        arguments["group_id"] = f.groups[1].id
    elif change == "foreign_actor":
        f.actor.agency_id = f.agencies[1].id
    elif change == "nonapproved":
        f.passengers[0].status = "needs_review"
    elif change == "deleted_group":
        f.groups[0].status = "deleted"
    else:
        f.session.add(
            PassportRosterResolutionModel(
                id=uuid.uuid4(),
                agency_id=f.agencies[0].id,
                client_group_id=f.groups[0].id,
                submission_id=f.passengers[0].id,
                resolution_type="rejected",
                status="active",
                resolved_by_user_id=f.actor.id,
            )
        )
    await f.session.flush()
    before = await counts(f)
    with pytest.raises((MCPAuthError, ValueError)):
        await service(f).qr(f.principal, **arguments)
    assert await counts(f) == before


async def test_attendance_alias_events_page_without_claiming_distinct_physical_presence(evidence):
    f = evidence
    before = await counts(f)
    first = await service(f).attendance(f.principal, **attendance_arguments(f), page_size=2)
    second = await service(f).attendance(
        f.principal, **attendance_arguments(f), page_size=2, cursor=first["next_cursor"]
    )
    items = first["items"] + second["items"]
    assert len(items) == 3 and len({item["passenger_id"] for item in items}) == 2
    assert {item["session_id"] for item in items} == {str(f.activity.id), str(f.alias.id)}
    assert first["completeness"] == "partial" and second["completeness"] == "complete"
    assert items[-1]["sync_source"] == "offline" and "No physical presence" in first["notice"]
    assert first["consistency"]["snapshot_guaranteed"] is False
    assert "PRIVATE" not in json.dumps(first) + json.dumps(second)
    assert await counts(f) == before


@pytest.mark.parametrize("change", ["page_size", "alias", "forged", "other_actor"])
async def test_attendance_cursor_binds_scope_actor_activity_and_page_filters(evidence, change):
    f = evidence
    first = await service(f).attendance(f.principal, **attendance_arguments(f), page_size=1)
    arguments = {**attendance_arguments(f), "page_size": 1, "cursor": first["next_cursor"]}
    principal = f.principal
    if change == "page_size":
        arguments["page_size"] = 2
    elif change == "alias":
        arguments["activity_id"] = f.alias.id
    elif change == "forged":
        arguments["cursor"] = first["next_cursor"][:-2] + "xx"
    else:
        principal = replace(f.principal, user_id=uuid.uuid4())
    with pytest.raises((ValueError, MCPAuthError)):
        await service(f).attendance(principal, **arguments)


async def test_attendance_keeps_removed_event_without_disclosing_removed_person_name(evidence):
    f = evidence
    f.session.add(
        PassportRosterResolutionModel(
            id=uuid.uuid4(),
            agency_id=f.agencies[0].id,
            client_group_id=f.groups[0].id,
            submission_id=f.passengers[0].id,
            resolution_type="rejected",
            status="active",
            resolved_by_user_id=f.actor.id,
        )
    )
    await f.session.flush()
    result = await service(f).attendance(f.principal, **attendance_arguments(f))
    assert len(result["items"]) == 3
    removed = [item for item in result["items"] if item["passenger_id"] == str(f.passengers[0].id)]
    assert len(removed) == 2 and all(item["passenger_name"] is None for item in removed)


async def test_native_sdk_read_image_is_committed_audited_and_section_denial_has_no_image(
    evidence, monkeypatch
):
    f = evidence
    await f.session.commit()
    app, server = FastAPI(), MCPServer("Existing evidence fixture")

    @asynccontextmanager
    async def sessions():
        try:
            yield f.session
        except BaseException:
            await f.session.rollback()
            raise

    app.state.mcp_session_factory = sessions
    register_tour_evidence_tools(server, app, f.settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=f.tokens[0],
            client_id=f.grants[0].client_id,
            scopes=["mcp:read"],
            subject=str(f.actor.id),
        ),
    )
    arguments = {key: str(value) for key, value in qr_arguments(f).items()}
    result = await server.call_tool("get_passenger_qr", arguments)
    assert not result.is_error and any(block.type == "image" for block in result.content)
    metadata = json.loads(result.content[0].text)
    audit = await f.session.get(AuditLogModel, uuid.UUID(metadata["audit_id"]))
    assert audit.result == "success" and f.qr.qr_payload not in json.dumps(audit.metadata_json)
    control = await f.session.get(MCPControlModel, 1)
    control.allowed_read_sections = ["all_groups"]
    await f.session.commit()
    denied = await server.call_tool("get_passenger_qr", arguments)
    assert denied.is_error and all(block.type != "image" for block in denied.content)
    assert json.loads(denied.content[0].text)["error"] == "access_denied"
    assert await f.session.scalar(select(func.count()).select_from(PassengerQRTokenModel)) == 1
