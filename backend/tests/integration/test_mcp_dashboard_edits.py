"""Canonical edit behavior, stale revisions, atomic receipts and retained history."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from sqlalchemy import func, select

from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPOperationError,
    MCPOperationService,
)
from app.core.config.mcp import MCPSettings
from app.domain.mcp_section_permissions import SUPPORTED_WRITE_SECTIONS, WRITE_TOOL_SECTIONS
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.menu_models import MenuCategoryModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.presentation.mcp.broadcast_write_tools import (
    broadcast_write_operation,
    register_broadcast_write_tools,
)
from app.presentation.mcp.dashboard_edit_models import EDIT_MODELS
from app.presentation.mcp.dashboard_edit_operations import dashboard_edit_operation
from app.presentation.mcp.dashboard_edit_tools import register_dashboard_edit_tools
from app.presentation.mcp.dashboard_write_support import configuration_revision
from app.presentation.mcp.document_assignment_tools import (
    DocumentAssignmentSelection,
    assignment_snapshot,
    document_assignment_operation,
)
from app.presentation.mcp.group_change_tools import MCPCreateGroupRequest
from tests.integration.test_mcp_operations import seed_identity


@pytest.fixture
async def edits(db_session, test_settings):
    settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True)})
    db_session.add(MCPControlModel(id=1, enabled=True, write_enabled=True,
        allowed_write_sections=sorted(SUPPORTED_WRITE_SECTIONS), allowed_write_tools=sorted(WRITE_TOOL_SECTIONS)))
    actor, grants, tokens = await seed_identity(db_session, settings)
    for grant in grants:
        grant.write_enabled = True
        grant.allowed_write_sections = sorted(SUPPORTED_WRITE_SECTIONS)
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic tenant", email="edits@example.test")
    db_session.add(agency)
    await db_session.flush()
    category = MenuCategoryModel(id=uuid.uuid4(), agency_id=agency.id, name="Original", normalized_name="original")
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, created_by_user_id=actor.id,
        name="Synthetic group", token="NEVER_RETURN_UPLOAD_CREDENTIAL", import_only=False,
        destination="Tokyo", travel_date=datetime.now(UTC).date(), return_date=(datetime.now(UTC)+timedelta(days=4)).date())
    db_session.add_all([category, group])
    await db_session.flush()
    return db_session, settings, actor, grants, tokens, agency, category, group


def edit_service(fixture, name):
    return MCPOperationService(fixture[0], fixture[1], [dashboard_edit_operation(name)])


async def execute(fixture, name, payload, *, key="dashboard-edits-stable-key-001", connection=0):
    return await edit_service(fixture, name).execute(access_token=fixture[4][connection], operation_name=name,
        idempotency_key=key, payload=payload)


async def test_menu_rename_replays_once_retains_before_and_rejects_stale_update(edits):
    session, _, _, _, _, agency, category, _ = edits
    payload = {"agency_id": str(agency.id), "category_id": str(category.id), "name": "Chosen new name", "expected_updated_at": category.updated_at.isoformat()}
    result = await execute(edits, "update_menu_category", payload)
    await session.commit()
    assert category.name == "Chosen new name"
    replay = await execute(edits, "update_menu_category", payload, connection=1)
    assert result == replay
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    history = await session.scalar(select(AuditLogModel).where(AuditLogModel.action == "mcp.dashboard_edit"))
    assert history.metadata_json["retained_before"]["target"]["name"] == "Original"
    with pytest.raises(MCPOperationError, match="workflow_revision_changed"):
        await execute(edits, "update_menu_category", {**payload, "name": "Stale overwrite"}, key="different-intended-edit-001")
    assert category.name == "Chosen new name"
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1


async def test_canonical_invalid_edit_rolls_back_history_and_receipt(edits):
    session, _, _, _, _, agency, category, _ = edits
    with pytest.raises(MCPOperationError, match="invalid_dashboard_edit"):
        await execute(edits, "update_menu_category", {"agency_id": str(agency.id), "category_id": str(category.id),
            "name": "   ", "expected_updated_at": category.updated_at.isoformat()})
    assert category.name == "Original"
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    assert await session.scalar(select(func.count()).select_from(AuditLogModel)) == 0


async def test_cross_tenant_target_and_moved_receipt_are_denied(edits):
    session, _, _, _, _, agency, category, _ = edits
    other = AgencyModel(id=uuid.uuid4(), name="Other synthetic", email="other-edits@example.test")
    session.add(other)
    await session.flush()
    payload = {"agency_id": str(agency.id), "category_id": str(category.id), "name": "Selected", "expected_updated_at": category.updated_at.isoformat()}
    with pytest.raises(MCPOperationError, match="workflow_resource_unavailable"):
        await execute(edits, "update_menu_category", {**payload, "agency_id": str(other.id)})
    result = await execute(edits, "update_menu_category", payload)
    category.agency_id = other.id
    await session.flush()
    with pytest.raises(MCPOperationError, match="workflow_receipt_unavailable"):
        await edit_service(edits, "update_menu_category").inspect(access_token=edits[4][0], operation_id=uuid.UUID(result["operation_id"]))


async def test_group_settings_keep_credentials_out_of_result_and_history(edits):
    session, _, _, _, _, agency, _, group = edits
    payload = {"agency_id": str(agency.id), "group_id": str(group.id), "name": "Chosen group",
        "expected_configuration_revision": configuration_revision(group), "collection_settings_confirmed": True,
        "base_city_enabled": True, "custom_details": [{"id": str(uuid.uuid4()), "label": "Chosen extra detail", "enabled": True, "required": False}]}
    result = await execute(edits, "configure_group_link", payload)
    assert group.base_city_enabled is True
    assert "NEVER_RETURN_UPLOAD_CREDENTIAL" not in json.dumps(result)
    audit = await session.scalar(select(AuditLogModel).where(AuditLogModel.action == "mcp.dashboard_edit"))
    assert "NEVER_RETURN_UPLOAD_CREDENTIAL" not in json.dumps(audit.metadata_json)


async def test_broadcast_creation_uses_canonical_deduplication_and_never_queues_sends(edits):
    session, settings, _, _, tokens, agency, _, _ = edits
    definition = broadcast_write_operation("create_whatsapp_broadcast")
    service = MCPOperationService(session, settings, [definition])
    payload = {"agency_id": str(agency.id), "name": "Synthetic broadcast", "organizing_company_name": "Fixture",
        "contacts": [{"name": "Synthetic person", "phone_number": "+919999999901"}, {"name": "Duplicate", "phone_number": "919999999901"}],
        "support_contacts": [{"name": "Synthetic support", "phone_number": "+919999999902"}], "recipient_opt_in_confirmed": True}
    first = await service.execute(access_token=tokens[0], operation_name=definition.policy.name, idempotency_key="broadcast-stable-key-001", payload=payload)
    await session.commit()
    replay = await service.execute(access_token=tokens[1], operation_name=definition.policy.name, idempotency_key="broadcast-stable-key-001", payload=payload)
    assert replay == first and first["data"]["messages_sent"] == 0
    assert await session.scalar(select(func.count()).select_from(WhatsAppBroadcastGroupModel)) == 1
    assert await session.scalar(select(func.count()).select_from(WhatsAppBroadcastRecipientModel)) == 1
    assert await session.scalar(select(func.count()).select_from(WhatsAppMessageLogModel)) == 0


async def test_sdk_registry_exposes_real_strict_models_and_collection_choices(test_settings):
    server, app = MCPServer("synthetic-edits"), FastAPI()
    app.state.mcp_operations = {}
    register_dashboard_edit_tools(server, app, test_settings)
    register_broadcast_write_tools(server, app, test_settings)
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert set(EDIT_MODELS) <= tools.keys()
    schema = tools["configure_group_link"].input_schema
    assert "GroupLinkEdit" in schema["$defs"]
    model = schema["$defs"]["GroupLinkEdit"]
    assert model["additionalProperties"] is False
    assert "expected_configuration_revision" in model["required"]
    assert "collection_settings_confirmed" in MCPCreateGroupRequest.model_json_schema()["required"]
    assert "custom_questions" in MCPCreateGroupRequest.model_json_schema()["properties"]


async def test_document_lane_save_rejects_assignment_drift_and_never_invents_match_or_delivery(edits):
    session, settings, _, _, tokens, agency, _, group = edits
    batches = [DocumentDistributionBatchModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        document_type="flight_ticket", status="draft", uploaded_count=1, rejected_count=0, matched_count=0) for _ in range(2)]
    session.add_all(batches)
    await session.flush()
    document = DistributedDocumentModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        batch_id=batches[0].id, document_type="flight_ticket", original_filename="synthetic.pdf",
        storage_key="PRIVATE_SYNTHETIC_STORAGE_KEY", detected_type="flight_ticket", match_status="needs_review", match_confidence=0)
    session.add(document)
    await session.flush()
    service = MCPOperationService(session, settings, [document_assignment_operation()])
    principal = await service._authorize(tokens[0], "mcp:change", tool_name="save_document_assignments")
    selection = DocumentAssignmentSelection(agency_id=agency.id, group_id=group.id, document_type="flight_ticket")
    context = MCPDatabaseContext(session, principal, uuid.UUID(int=0))
    *_, preview, revision = await assignment_snapshot(context, selection, lock=False)
    assert "PRIVATE_SYNTHETIC_STORAGE_KEY" not in json.dumps(preview)
    document.match_confidence = 0.5
    await session.flush()
    payload = {**selection.model_dump(mode="json"), "inspected_revision": revision, "assignments_reviewed": True}
    with pytest.raises(MCPOperationError, match="document_assignment_revision_changed"):
        await service.execute(access_token=tokens[0], operation_name="save_document_assignments", idempotency_key="document-save-stable-key-001", payload=payload)
    assert all(row.status == "draft" for row in batches)
    *_, fresh = await assignment_snapshot(context, selection, lock=False)
    result = await service.execute(access_token=tokens[0], operation_name="save_document_assignments", idempotency_key="document-save-stable-key-001", payload={**payload, "inspected_revision": fresh})
    assert all(row.status == "saved" for row in batches)
    assert document.passenger_id is None and document.match_status == "needs_review"
    assert result["data"]["documents_sent"] == 0
    assert await session.scalar(select(func.count()).select_from(DocumentWhatsAppDeliveryModel)) == 0
