"""Real persistence and SDK checks for sparse, history-preserving MCP corrections."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import delete, func, select

from app.application.mcp.client_detail_changes import CLIENT_DETAIL_POLICY, client_detail_operation
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.mcp_record_revision_models import MCPRecordRevisionModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
)
from app.presentation.mcp.client_detail_tools import (
    register_client_detail_tools,
    validate_client_detail_changes,
)
from app.presentation.mcp.invocation import MCPInputError
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def detail_fixture(operations_fixture):
    session, settings, _, grants, _ = operations_fixture
    for grant in grants:
        grant.capabilities = ["mcp:read", "mcp:change"]
    agency = AgencyModel(id=uuid.uuid4(), name="Detail tenant", email="details@example.test")
    session.add(agency)
    await session.flush()
    question, detail = str(uuid.uuid4()), str(uuid.uuid4())
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Saved group",
        token=uuid.uuid4().hex,
        status="active",
        agent_employee_code_enabled=True,
        custom_questions=[
            {
                "id": question,
                "label": "Transport",
                "enabled": True,
                "required": False,
                "options": ["Bus", "Train"],
            }
        ],
        custom_details=[{"id": detail, "label": "Pickup note", "enabled": True, "required": False}],
    )
    session.add(group)
    await session.flush()
    submission = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        group_id=group.id,
        client_name="Original name",
        client_email="original@example.test",
        client_phone="9876543210",
        image_s3_key="private/original-passport.jpg",
        status="ai_approved",
        extraction_status="extraction_complete",
        updated_at=datetime.now(UTC),
        confirmed_fields={"passport_number": "PRIVATE-P123", "agent_employee_code": "OLD-7"},
        extracted_fields={"passport_number": "PRIVATE-P123", "producer_code": "OCR-OLD"},
        staff_metadata={"producer_code": "OLD-7", "unrelated": "keep"},
        custom_answers=[
            {"question_id": question, "label": "Original transport label", "value": "Bus"}
        ],
        custom_detail_answers=[
            {"detail_id": detail, "label": "Original pickup label", "value": "North door"}
        ],
    )
    session.add(submission)
    await session.flush()
    payload = {
        "submission_id": str(submission.id),
        "changes": {
            "expected_updated_at": submission.updated_at.isoformat(),
            "client_email": "corrected@example.com",
        },
    }
    service = MCPOperationService(
        session, settings, [client_detail_operation(validate_client_detail_changes)]
    )
    return operations_fixture, group, submission, payload, service


async def correct(fixture, *, payload=None, key="client-details-edit-001", connection=0):
    return await fixture[4].execute(
        access_token=fixture[0][4][connection],
        operation_name=CLIENT_DETAIL_POLICY.name,
        idempotency_key=key,
        payload=fixture[3] if payload is None else payload,
    )


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def test_sparse_correction_history_exact_replay_and_original_passport_preserved(
    detail_fixture,
):
    fixture = detail_fixture
    session, submission = fixture[0][0], fixture[2]
    before = (
        submission.extracted_fields.copy(),
        submission.image_s3_key,
        submission.status,
        submission.extraction_status,
        submission.client_phone,
    )
    first = await correct(fixture)
    await session.refresh(submission)
    assert submission.client_email == "corrected@example.com"
    assert (
        submission.extracted_fields,
        submission.image_s3_key,
        submission.status,
        submission.extraction_status,
        submission.client_phone,
    ) == before
    revision = await session.scalar(select(MCPRecordRevisionModel))
    assert revision.operation_id == uuid.UUID(first["operation_id"])
    assert revision.before_values["client_email"]["direct"] == "original@example.test"
    assert revision.after_values["client_email"]["direct"] == "corrected@example.com"
    assert set(revision.before_values) == {"client_email"}
    assert "PRIVATE-P123" not in json.dumps(revision.before_values) + json.dumps(
        revision.after_values
    )
    assert "original@example.test" not in json.dumps(
        first
    ) and "corrected@example.com" not in json.dumps(first)
    # A subsequent manual edit does not get overwritten by retrying old input.
    submission.client_email = "later@example.test"
    await session.flush()
    assert await correct(fixture, connection=1) == first
    assert submission.client_email == "later@example.test"
    assert await count(session, MCPRecordRevisionModel) == 1
    assert await count(session, MCPOperationModel) == 1
    audits = list((await session.scalars(select(AuditLogModel))).all())
    assert len(audits) == 1
    assert audits[0].metadata_json["changed_fields"] == ["client_email"]
    assert "@example" not in json.dumps(audits[0].metadata_json)


async def test_changed_scalar_aliases_and_custom_values_retain_only_changed_before_images(
    detail_fixture,
):
    fixture = detail_fixture
    question = fixture[2].custom_answers[0]["question_id"]
    payload = {
        **fixture[3],
        "changes": {
            "expected_updated_at": fixture[3]["changes"]["expected_updated_at"],
            "agent_employee_code": "NEW-9",
            "custom_answers": [{"question_id": question, "value": "Train"}],
        },
    }
    await correct(fixture, payload=payload)
    session = fixture[0][0]
    await session.refresh(fixture[2])
    revision = await session.scalar(select(MCPRecordRevisionModel))
    assert revision.before_values["agent_employee_code"]["confirmed_fields"] == {
        "agent_employee_code": "OLD-7"
    }
    assert revision.before_values["agent_employee_code"]["staff_metadata"] == {
        "producer_code": "OLD-7"
    }
    assert revision.after_values["agent_employee_code"]["staff_metadata"] == {
        "producer_code": "NEW-9"
    }
    assert revision.before_values[f"question_id:{question}"]["value"] == "Bus"
    assert revision.after_values[f"question_id:{question}"]["value"] == "Train"
    assert fixture[2].custom_answers[0]["label"] == "Original transport label"
    assert fixture[2].custom_detail_answers[0]["value"] == "North door"
    assert fixture[2].extracted_fields["producer_code"] == "OCR-OLD"


async def test_legacy_effective_detail_history_does_not_copy_raw_passport_fields(detail_fixture):
    fixture = detail_fixture
    fixture[2].confirmed_fields = None
    await fixture[0][0].flush()
    version = fixture[2].updated_at.isoformat()
    await correct(
        fixture,
        payload={
            **fixture[3],
            "changes": {
                "expected_updated_at": version,
                "agent_employee_code": "NEW-9",
            },
        },
    )
    revision = await fixture[0][0].scalar(select(MCPRecordRevisionModel))
    assert revision.before_values["agent_employee_code"]["value"] == "OCR-OLD"
    assert "PRIVATE-P123" not in json.dumps(revision.after_values)
    await fixture[0][0].refresh(fixture[2])
    assert fixture[2].confirmed_fields["passport_number"] == "PRIVATE-P123"


@pytest.mark.parametrize(
    "changes",
    [
        {"client_phone": None},
        {"client_phone": " "},
        {"agent_employee_code": ""},
        {"custom_answers": []},
        {"client_email": "not-an-email"},
        {"status": "confirmed"},
        {"confirmed_fields": {"passport_number": "replace"}},
        {"image_s3_key": "replace"},
        {"expected_updated_at": "2026-09-29T12:00:00"},
    ],
)
async def test_invalid_or_destructive_input_never_writes(detail_fixture, changes):
    fixture = detail_fixture
    payload = {**fixture[3], "changes": {**fixture[3]["changes"], **changes}}
    with pytest.raises(MCPInputError):
        await correct(fixture, payload=payload)
    assert await count(fixture[0][0], MCPOperationModel) == 0
    assert await count(fixture[0][0], MCPRecordRevisionModel) == 0
    await fixture[0][0].refresh(fixture[2])
    assert fixture[2].client_email == "original@example.test"


@pytest.mark.parametrize(
    "kind", ["stale", "unknown_custom", "invalid_phone", "invalid_option", "blank_custom"]
)
async def test_business_validation_is_all_or_nothing(detail_fixture, kind):
    fixture = detail_fixture
    changes = dict(fixture[3]["changes"])
    if kind == "stale":
        changes["expected_updated_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    elif kind == "unknown_custom":
        changes["custom_answers"] = [{"question_id": str(uuid.uuid4()), "value": "Train"}]
    elif kind == "invalid_phone":
        changes["client_phone"] = "bad-phone"
    else:
        changes["custom_answers"] = [
            {
                "question_id": fixture[2].custom_answers[0]["question_id"],
                "value": " " if kind == "blank_custom" else "Plane",
            }
        ]
    with pytest.raises((MCPOperationError, MCPInputError)):
        await correct(fixture, payload={**fixture[3], "changes": changes})
    assert await count(fixture[0][0], MCPOperationModel) == 0
    assert await count(fixture[0][0], MCPRecordRevisionModel) == 0
    await fixture[0][0].refresh(fixture[2])
    assert fixture[2].client_email == "original@example.test"


@pytest.mark.parametrize("status", ["queued", "processing", "delivery_unknown"])
async def test_pending_private_delivery_blocks_without_cancellation(detail_fixture, status):
    fixture = detail_fixture
    delivery = DocumentWhatsAppDeliveryModel(
        id=uuid.uuid4(),
        agency_id=fixture[1].agency_id,
        group_id=fixture[1].id,
        passenger_id=fixture[2].id,
        send_batch_id=uuid.uuid4(),
        document_type="flight_ticket",
        document_filename="ticket.pdf",
        passenger_name="Original",
        phone_number="+919876543210",
        normalized_phone_number="+919876543210",
        template_name="private",
        status=status,
    )
    fixture[0][0].add(delivery)
    await fixture[0][0].flush()
    with pytest.raises(MCPOperationError, match="client_details_delivery_pending"):
        await correct(fixture)
    await fixture[0][0].refresh(delivery)
    assert delivery.status == status and delivery.error_message is None
    assert await count(fixture[0][0], MCPRecordRevisionModel) == 0


async def test_failure_after_update_rolls_back_history_business_audit_and_receipt(
    detail_fixture, monkeypatch
):
    fixture = detail_fixture
    monkeypatch.setattr(
        "app.application.use_cases.passports.client_details_transaction.propagate_mobile_passenger_change",
        AsyncMock(side_effect=RuntimeError("synthetic propagation failure")),
    )
    with pytest.raises(RuntimeError, match="synthetic propagation"):
        await correct(fixture)
    for model in (MCPRecordRevisionModel, MCPOperationModel, AuditLogModel):
        assert await count(fixture[0][0], model) == 0
    await fixture[0][0].refresh(fixture[2])
    assert fixture[2].client_email == "original@example.test"


async def test_noop_does_not_create_fake_revision_or_change_timestamp(detail_fixture):
    fixture = detail_fixture
    result = await correct(
        fixture,
        payload={
            **fixture[3],
            "changes": {
                "expected_updated_at": fixture[3]["changes"]["expected_updated_at"],
                "client_phone": "9876543210",
            },
        },
    )
    assert result["data"]["changed_fields"] == [] and result["data"]["record_revision_id"] is None
    assert await count(fixture[0][0], MCPRecordRevisionModel) == 0


@pytest.mark.parametrize("loss", ["removed", "archived", "role", "capability"])
async def test_current_entity_and_grant_authority_required_for_replay_and_inspection(
    detail_fixture, loss
):
    fixture = detail_fixture
    receipt = await correct(fixture)
    session = fixture[0][0]
    if loss == "removed":
        await session.execute(
            delete(PassportSubmissionModel).where(PassportSubmissionModel.id == fixture[2].id)
        )
    elif loss == "archived":
        fixture[1].status = "archived"
    elif loss == "role":
        fixture[0][2].role = "agency_admin"
    else:
        fixture[0][3][1].capabilities = ["mcp:read"]
    await session.flush()
    with pytest.raises(MCPAuthError):
        await correct(fixture, connection=1)
    with pytest.raises(MCPAuthError):
        await fixture[4].inspect(
            access_token=fixture[0][4][1], operation_id=uuid.UUID(receipt["operation_id"])
        )


async def test_changed_idempotent_payload_conflicts_without_overwrite(detail_fixture):
    fixture = detail_fixture
    await correct(fixture)
    with pytest.raises(MCPOperationError, match="idempotency_conflict"):
        await correct(
            fixture,
            payload={
                **fixture[3],
                "changes": {**fixture[3]["changes"], "client_email": "other@example.com"},
            },
        )
    assert await count(fixture[0][0], MCPRecordRevisionModel) == 1


async def test_new_intended_correction_appends_history_and_preserves_earlier_revision(
    detail_fixture,
):
    fixture = detail_fixture
    first = await correct(fixture)
    first_revision = await fixture[0][0].scalar(select(MCPRecordRevisionModel))
    saved_before, saved_after = (
        json.dumps(first_revision.before_values),
        json.dumps(first_revision.after_values),
    )
    second = await correct(
        fixture,
        key="explicit-new-correction-002",
        payload={
            **fixture[3],
            "changes": {
                "expected_updated_at": first["data"]["updated_at"],
                "client_email": "second@example.com",
            },
        },
    )
    assert second["data"]["record_revision_id"] != first["data"]["record_revision_id"]
    assert await count(fixture[0][0], MCPRecordRevisionModel) == 2
    await fixture[0][0].refresh(first_revision)
    assert json.dumps(first_revision.before_values) == saved_before
    assert json.dumps(first_revision.after_values) == saved_after


async def test_sdk_descriptors_correction_commit_and_replay_share_real_boundaries(
    detail_fixture, monkeypatch
):
    fixture = detail_fixture
    session, settings, actor, grants, tokens = fixture[0]
    await session.commit()
    app = FastAPI()

    @asynccontextmanager
    async def sessions():
        yield session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    server = MCPServer("Client detail fixture")
    register_client_detail_tools(app, server, settings)
    current = [0]

    def token():
        index = current[0]
        return AccessToken(
            token=tokens[index],
            client_id=grants[index].client_id,
            scopes=["mcp:read", "mcp:change"],
            subject=str(actor.id),
            resource=settings.mcp.resource,
            claims={"grant_id": str(grants[index].id)},
        )

    monkeypatch.setattr("app.presentation.mcp.invocation.get_access_token", token)
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert tools["inspect_client_details"].meta == {"capability": "mcp:read"}
    assert tools["correct_client_details"].meta == {"capability": "mcp:change"}
    descriptor = (
        await server.call_tool("inspect_client_details", {"submission_id": str(fixture[2].id)})
    ).structured_content
    assert "PRIVATE-P123" not in json.dumps(descriptor) and "private/original" not in json.dumps(
        descriptor
    )
    version = descriptor["details"]["updated_at"]
    if not version.endswith("Z") and "+" not in version:
        version += "Z"
    arguments = {
        "submission_id": str(fixture[2].id),
        "changes": {"expected_updated_at": version, "client_phone": "9876543211"},
        "idempotency_key": "sdk-correction-request-001",
    }
    first = (await server.call_tool("correct_client_details", arguments)).structured_content
    assert "receipt" in first, first
    current[0] = 1
    second = (await server.call_tool("correct_client_details", arguments)).structured_content
    assert first["receipt"] == second["receipt"] and first["audit_id"] != second["audit_id"]
    assert not session.in_transaction()
    assert await count(session, MCPRecordRevisionModel) == 1
    await session.refresh(fixture[2])
    assert fixture[2].client_phone == "+919876543211"
