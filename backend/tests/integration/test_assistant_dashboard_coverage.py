"""Transcript regressions through the actual read adapters and native tool loop."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event, update

from app.application.assistant.contracts import AssistantError
from app.application.assistant.settings_contracts import (
    AssistantConfiguration,
    AssistantSettingsUpdate,
)
from app.core.assistant_config import AssistantSettings
from app.domain.entities.entities import UserRole
from app.infrastructure.assistant.settings_store import save_settings
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import (
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.presentation.assistant import reads
from app.presentation.assistant.catalog import ASSISTANT_READS, dashboard_handler
from app.presentation.assistant.native_session import NativeSession
from app.presentation.mcp.dashboard_read_tools import dashboard_parameters
from tests.integration.test_assistant_read_only import workspace as workspace


@pytest.fixture
async def populated(workspace):
    session, _, agency, _, group, _, _ = workspace
    people = [PassportSubmissionModel(id=uuid4(), agency_id=agency.id, group_id=group.id,
        client_name=name, client_email=f"person{index}@example.test", client_phone=f"+91900000000{index}",
        image_s3_key="private/fixture-passport", status="staff_approved",
        extracted_fields={"passport_number": f"FIXTURE{index}"},
        staff_metadata={"staff_code": f"STAFF{index}"})
        for index, name in enumerate(["Ada Fixture", "Zara Fixture"])]
    live = WhatsAppBroadcastGroupModel(id=uuid4(), agency_id=agency.id, name="Synthetic active WhatsApp topic")
    archived = WhatsAppBroadcastGroupModel(id=uuid4(), agency_id=agency.id, name="Archived topic", archived_at=datetime.now(UTC))
    session.add_all([*people, live, archived])
    await session.flush()
    session.add(WhatsAppBroadcastRecipientModel(id=uuid4(), agency_id=agency.id,
        broadcast_group_id=live.id, name="Ada Fixture", phone_number="+919000000000",
        normalized_phone_number="919000000000", imported_fields={"Department": "Operations"}))
    await session.commit()
    return workspace, people, live


@pytest.mark.parametrize("query, expected", [
    ("How many people are in there?", "passport_view"),
    ("participants headcount", "passport_view"),
    ("people personal details", "passport_details"),
    ("active WhatsApp topics", "whatsapp_groups"),
    ("WhatsApp message types", "whatsapp_message_topics"),
    ("companies clients", "companies"),
])
def test_natural_language_discovers_the_actual_reader(query, expected):
    result = reads.data_catalog(query)
    assert result["views"][0]["name"] == expected
    assert result["views"][0]["parameters"]["additionalProperties"] is False


def test_every_assistant_view_has_a_fixed_non_injected_input_schema():
    for definition in ASSISTANT_READS.values():
        schema = dashboard_parameters(definition, handler=dashboard_handler(definition))
        assert not {"current_user", "session", "user", "use_case", "settings"} & schema["properties"].keys()


async def test_counts_people_details_and_topics_are_observational_current_and_navigable(populated):
    workspace, people, live = populated
    session, actor, agency, _, group, request, _ = workspace
    reader = reads.DashboardReader(request, actor)
    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().casefold())
    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        overview = await reader.overview()
        assert "passport_view" in overview["capabilities"]["areas"]["group_people"]
        assert "whatsapp_groups" in overview["capabilities"]["areas"]["whatsapp"]
        params = {"group_id": str(group.id), "page_size": 1}
        roster = await reader.read("passport_view", params)
        assert roster["website_pagination"]["group_total"] == 2
        assert roster["website_pagination"]["total"] == 2
        assert roster["completeness"] == "partial"
        first = await reader.read("passport_view", params, data_path=["items", 0, "client_name"])
        assert first["data"] == "Ada Fixture"
        second = await reader.read("passport_view", {**params, "page": 2}, data_path=["items", 0, "client_name"])
        assert second["data"] == "Zara Fixture"
        detail = await reader.read("passport_details", {"submission_id": str(people[0].id)})
        assert "person0@example.test" in json.dumps(detail)
        fields = await reader.read("passport_details", {"submission_id": str(people[0].id)}, data_path=["staff_metadata"])
        assert fields["data"] == {"staff_code": "STAFF0"}
        assert "private/fixture-passport" not in json.dumps(detail)
        topics = await reader.read("whatsapp_groups", {}, agency_id=str(agency.id))
        assert topics["data"][0]["id"] == str(live.id)
        assert topics["data"][0]["recipient_count"] == 1
        assert "Archived topic" not in json.dumps(topics)
        message_types = await reader.read("whatsapp_message_topics", {})
        assert "welcome" in json.dumps(message_types)
        summary = await reader.read("dashboard_summary", {}, agency_id=str(agency.id))
        assert summary["data"]["total_passports"] == 2
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert not any(sql.startswith(("update ", "delete ", "insert ")) and not any(
        ledger in sql for ledger in ("audit_logs", "audit_chain_heads")) for sql in statements)
    await session.execute(update(PassportSubmissionModel).where(PassportSubmissionModel.id == people[0].id).values(client_name="Updated Ada"))
    await session.commit()
    fresh = await reader.read("passport_details", {"submission_id": str(people[0].id)}, data_path=["client_name"])
    assert fresh["data"] == "Updated Ada"


async def test_native_voice_uses_same_real_people_and_topic_readers(populated):
    workspace, people, _ = populated
    _, actor, agency, _, group, request, store = workspace
    sent = []
    async def send(message):
        sent.append(message)
    native = NativeSession(request, actor, AssistantSettings(_env_file=None), store, uuid4(), send)
    instructions, _ = await native.context()
    assert "personal data is not categorically blocked" in instructions
    results = await native.tool_calls([
        {"id": "people", "name": "read_dashboard", "args": {"view": "passport_view", "parameters": {"group_id": str(group.id)}, "data_path": ["group_total"]}},
        {"id": "detail", "name": "read_dashboard", "args": {"view": "passport_details", "parameters": {"submission_id": str(people[0].id)}, "data_path": ["client_email"]}},
        {"id": "topics", "name": "read_dashboard", "args": {"view": "whatsapp_groups", "parameters": {}, "agency_id": str(agency.id)}},
    ])
    assert results[0]["response"]["result"]["data"] == 2
    assert results[1]["response"]["result"]["data"] == "person0@example.test"
    assert "Synthetic active WhatsApp topic" in json.dumps(results[2])
    assert len([item for item in sent if item["type"] == "source"]) == 3


async def test_company_directory_summary_and_trips_use_canonical_agency_scope(workspace):
    session, actor, agency, other, group, request, _ = workspace
    company = ClientOrganizationModel(id=uuid4(), agency_id=agency.id,
        name="Fixture business", normalized_name="fixture business", status="active")
    session.add(company)
    await session.flush()
    group.company_id = company.id
    group.company_revision = 1
    await session.commit()
    reader = reads.DashboardReader(request, actor)
    with pytest.raises(AssistantError, match="select agency_id"):
        await reader.read("dashboard_summary", {})
    directory = await reader.read("companies", {}, agency_id=str(agency.id), data_path=["items"])
    assert directory["data"][0]["name"] == "Fixture business"
    summary = await reader.read("company_summary", {"company_id": str(company.id)})
    assert summary["data"]["total_groups"] == 1
    trips = await reader.read("company_groups", {"company_id": str(company.id)}, data_path=["items"])
    assert trips["data"][0]["name"] == "Synthetic departure"
    with pytest.raises(AssistantError, match="selected agency"):
        await reader.read("company_summary", {"company_id": str(company.id)}, agency_id=str(other.id))


async def test_delegated_grant_does_not_expand_whatsapp_or_cross_agency_access(workspace):
    session, actor, agency, other, _, request, _ = workspace
    await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=0,
        configuration=AssistantConfiguration(allowed_roles=["agency_admin"])))
    await session.execute(update(UserModel).where(UserModel.id == actor.id).values(role="agency_admin", agency_id=agency.id))
    await session.commit()
    delegated = replace(actor, role=UserRole.AGENCY_ADMIN, agency_id=agency.id)
    reader = reads.DashboardReader(request, delegated)
    overview = await reader.overview()
    assert "whatsapp" not in overview["capabilities"]["areas"]
    assert reads.data_catalog("whatsapp_groups", actor=delegated)["views"] == []
    with pytest.raises(AssistantError, match="outside your dashboard access"):
        await reader.read("whatsapp_groups", {})
    with pytest.raises(AssistantError, match="own agency"):
        await reader.read("dashboard_summary", {}, agency_id=str(other.id))
