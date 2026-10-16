"""Real roster matching, selection, durable queueing and dispatch without Meta calls."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.whatsapp import document_update_runtime, web_publication
from app.presentation.api.v1.routes import group_update_preview, group_updates
from app.presentation.dependencies.auth import get_current_active_user
from tests.integration.test_document_updates import document
from tests.persistence import persist_graph


@pytest.fixture
async def group_update(db_session, monkeypatch):
    await db_session.execute(text("DROP INDEX uq_whatsapp_active_explicit_resend"))
    agency = AgencyModel(id=uuid.uuid4(), name="Update agency", email="updates@example.test")
    actor = UserModel(id=uuid.uuid4(), agency_id=agency.id, role="agency_admin", email="admin@example.test",
                      hashed_password="unused", full_name="Staff", is_active=True)
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Trip", token=uuid.uuid4().hex)
    broadcast = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Excel contacts",
                                            recipient_opt_in_confirmed_at=datetime.now(UTC))
    link = ClientGroupWhatsAppBroadcastLinkModel(agency_id=agency.id, client_group_id=group.id,
                                               broadcast_group_id=broadcast.id, matching_field_keys=["staff_code"])
    recipients = [WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(), agency_id=agency.id, broadcast_group_id=broadcast.id, name=f"Contact {i}",
        phone_number=f"+9198765432{i:02}", normalized_phone_number=f"+9198765432{i:02}",
        imported_fields={"staff_code": f"EMP{i}"},
    ) for i in range(4)]
    passengers = [PassportSubmissionModel(
        id=uuid.uuid4(), agency_id=agency.id, group_id=group.id, client_name=f"Person {i}",
        client_phone=f"+9191234567{i:02}", client_reviewed_at=datetime.now(UTC),
        staff_metadata={"staff_code": f"EMP{i}"}, image_s3_key="test/passport", status="staff_approved",
    ) for i in range(3)]
    await persist_graph(db_session, [agency, actor, group, broadcast, link, *recipients, *passengers])
    monkeypatch.setattr(group_update_preview, "configured_template_name", AsyncMock(return_value="pending_v1"))
    monkeypatch.setattr(group_update_preview, "get_settings", lambda: SimpleNamespace(whatsapp_access_token="test", whatsapp_phone_number_id="test"))
    publish = AsyncMock(return_value=1)
    monkeypatch.setattr(web_publication, "run_whatsapp_send_publication", publish)
    monkeypatch.setattr(document_update_runtime, "AsyncSessionFactory", async_sessionmaker(db_session.bind, expire_on_commit=False))
    monkeypatch.setattr(document_update_runtime, "get_settings", lambda: SimpleNamespace(whatsapp_phone_number_id="test"))
    provider = AsyncMock(side_effect=lambda **kwargs: "wamid." + uuid.uuid4().hex)
    monkeypatch.setattr(document_update_runtime, "send_whatsapp_document_update_template", provider)
    app = FastAPI()
    app.include_router(group_updates.router)
    actor_entity = await UserRepository(db_session).get_by_id(actor.id)
    app.dependency_overrides[get_current_active_user] = lambda: actor_entity
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(session=db_session, agency=agency, group=group, broadcast=broadcast, link=link,
                              passengers=passengers, recipients=recipients, client=client, publish=publish, provider=provider)


async def preview(fixture, **audience):
    result = await fixture.client.post(f"/groups/{fixture.group.id}/updates/preview", json=audience)
    assert result.status_code == 200, result.text
    return result.json()


def request_for(data):
    return {"request_id": str(uuid.uuid4()), "preview_token": data["preview_token"], "audience": data["audience"],
            "audience_keys": [row["audience_key"] for row in data["recipients"] if row["eligible"]],
            "message_content": "Your visas\n\nare\tbeing processed."}


async def queue(fixture, data, expected=200):
    result = await fixture.client.post(f"/groups/{fixture.group.id}/updates/send", json=data)
    assert result.status_code == expected, result.text
    return result


async def test_submitted_uses_completed_number_and_missing_uses_excel(group_update):
    all_rows = (await preview(group_update))["recipients"]
    assert len(all_rows) == 4
    submitted = (await preview(group_update, submission_status="submitted"))["recipients"]
    missing = (await preview(group_update, submission_status="not_submitted"))["recipients"]
    assert len(submitted) == 3 and len(missing) == 1
    assert {row["phone_number"] for row in submitted} == {p.client_phone for p in group_update.passengers}
    assert all(row["phone_source"] == "submitted" for row in submitted)
    assert missing[0]["phone_number"] == group_update.recipients[3].normalized_phone_number
    assert missing[0]["phone_source"] == "imported"


@pytest.mark.parametrize("lane", ["visa", "flight_ticket", "flight_ticket_arrival", "flight_ticket_domestic", "flight_ticket_domestic_arrival"])
@pytest.mark.parametrize("accepted", ["submitted", "sent", "delivered", "read"])
async def test_filters_intersect_and_failed_unknown_missing_partial_remain_pending(group_update, lane, accepted):
    await document(group_update, 0, lane=lane, status=accepted)
    await document(group_update, 1, lane=lane, status="delivery_unknown")
    await document(group_update, 2, lane=lane, status="read")
    await document(group_update, 2, lane=lane, status="failed")
    sent = await preview(group_update, document_type=lane, document_status="sent")
    assert [row["name"] for row in sent["recipients"]] == ["Person 0"]
    pending = await preview(group_update, document_type=lane, document_status="pending")
    assert len(pending["recipients"]) == 3
    both = await preview(group_update, document_type=lane, document_status="pending", submission_status="submitted")
    assert {row["name"] for row in both["recipients"]} == {"Person 1", "Person 2"}


async def test_shared_verified_phone_is_deduplicated_and_request_is_idempotent(group_update):
    group_update.passengers[1].client_phone = group_update.passengers[0].client_phone
    await group_update.session.commit()
    payload = request_for(await preview(group_update))
    result = await queue(group_update, payload)
    assert result.json()["queued_count"] == 3
    assert result.json()["passenger_count"] == 4
    assert (await queue(group_update, payload)).json() == result.json()
    logs = list((await group_update.session.scalars(select(WhatsAppMessageLogModel))).all())
    assert len(logs) == 3
    assert all(log.template_parameter_values == ["Your visas are being processed."] for log in logs)
    assert all(log.document_update_context["audience_version"] == 2 for log in logs)
    assert group_update.publish.await_count == 1
    await queue(group_update, {**payload, "message_content": "Different"}, expected=409)
    data = await preview(group_update)
    assert not any(row["eligible"] for row in data["recipients"])
    group_update.provider.assert_not_awaited()


@pytest.mark.parametrize("change", ["phone", "removed", "consent", "filter", "archive"])
async def test_stale_sources_cannot_queue(group_update, change):
    payload = request_for(await preview(group_update))
    if change == "phone":
        group_update.passengers[0].client_phone = "+919999888777"
    elif change == "removed":
        group_update.recipients[0].removed_at = datetime.now(UTC)
    elif change == "consent":
        group_update.broadcast.recipient_opt_in_confirmed_at = None
    elif change == "archive":
        group_update.group.status = "archived"
    else:
        payload["audience"]["submission_status"] = "not_submitted"
    await group_update.session.commit()
    await queue(group_update, payload, expected=409)
    assert not list((await group_update.session.scalars(select(WhatsAppMessageLogModel))).all())
    group_update.publish.assert_not_awaited()


async def test_missing_verified_phone_never_falls_back_to_imported_contact(group_update):
    group_update.passengers[0].client_phone = None
    await group_update.session.commit()
    data = await preview(group_update, submission_status="submitted")
    row = next(row for row in data["recipients"] if row["name"] == "Person 0")
    assert row["phone_number"] is None and not row["eligible"]
    assert "fallback" in row["reason"]


async def test_excel_passport_record_is_not_a_completed_submission_but_keeps_document_status(group_update):
    person = group_update.passengers[0]
    person.image_s3_key = "excel-imports/person"
    person.confidence_score = {"source": "excel_import"}
    await group_update.session.commit()
    await document(group_update, 0, status="sent")
    data = await preview(group_update, submission_status="not_submitted", document_status="sent")
    assert len(data["recipients"]) == 1
    row = data["recipients"][0]
    assert row["phone_number"] == group_update.recipients[0].normalized_phone_number
    assert row["phone_source"] == "imported"


async def test_worker_sends_all_audience_including_imported_numbers_once(group_update):
    await queue(group_update, request_for(await preview(group_update)))
    batch = await group_update.session.scalar(select(WhatsAppMessageLogModel.batch_id))
    await document_update_runtime.run_document_update_broadcast(batch_id=str(batch))
    await document_update_runtime.run_document_update_broadcast(batch_id=str(batch))
    assert group_update.provider.await_count == 4
    assert {call.kwargs["to_number"] for call in group_update.provider.await_args_list} == {
        *(p.client_phone for p in group_update.passengers), group_update.recipients[3].normalized_phone_number,
    }


@pytest.mark.parametrize("change", ["submitted", "phone", "document", "unlink", "consent"])
async def test_worker_rechecks_selected_audience_and_never_reroutes(group_update, change):
    filters = {"submission_status": "not_submitted"} if change == "submitted" else {"submission_status": "submitted", "document_status": "pending"}
    data = await preview(group_update, **filters)
    payload = request_for(data)
    payload["audience_keys"] = [data["recipients"][0]["audience_key"]]
    await queue(group_update, payload)
    batch = await group_update.session.scalar(select(WhatsAppMessageLogModel.batch_id))
    if change == "submitted":
        p = group_update.passengers[0]
        group_update.session.add(PassportSubmissionModel(
            id=uuid.uuid4(), agency_id=p.agency_id, group_id=p.group_id, client_name="New person",
            client_phone="+919555555555", client_reviewed_at=datetime.now(UTC), staff_metadata={"staff_code": "EMP3"},
            status="staff_approved", image_s3_key="test/new",
        ))
    elif change == "phone":
        group_update.passengers[0].client_phone = "+919999888777"
    elif change == "document":
        await document(group_update, 0, status="sent")
    elif change == "unlink":
        await group_update.session.delete(group_update.link)
    else:
        group_update.broadcast.recipient_opt_in_confirmed_at = None
    await group_update.session.commit()
    await document_update_runtime.run_document_update_broadcast(batch_id=str(batch))
    group_update.provider.assert_not_awaited()
    status = await group_update.session.scalar(select(WhatsAppMessageLogModel.status))
    assert status == "skipped"


async def test_cross_tenant_group_and_injected_contacts_are_rejected(group_update):
    foreign = AgencyModel(id=uuid.uuid4(), name="Other", email="other@example.test")
    other_group = ClientGroupModel(id=uuid.uuid4(), agency_id=foreign.id, name="Other trip", token=uuid.uuid4().hex)
    await persist_graph(group_update.session, [foreign, other_group])
    result = await group_update.client.post(f"/groups/{other_group.id}/updates/preview", json={})
    assert result.status_code == 404
    payload = request_for(await preview(group_update))
    payload["audience_keys"] = ["recipient:" + str(uuid.uuid4())]
    await queue(group_update, payload, expected=409)


async def test_ambiguous_match_is_excluded_instead_of_using_an_imported_fallback(group_update):
    group_update.recipients[1].imported_fields = {"staff_code": "EMP0"}
    await group_update.session.commit()
    data = await preview(group_update)
    ambiguous = [row for row in data["recipients"] if row["submission_status"] == "needs_review"]
    assert len(ambiguous) == 2
    assert all(not row["eligible"] for row in ambiguous)


async def unmatched_completed(fixture, phone="+919444555666"):
    passenger = PassportSubmissionModel(
        id=uuid.uuid4(), agency_id=fixture.agency.id, group_id=fixture.group.id,
        client_name="Submitted without Excel contact", client_phone=phone,
        client_reviewed_at=datetime.now(UTC), staff_metadata={"staff_code": "NO-EXCEL-ROW"},
        image_s3_key="test/direct", status="staff_approved",
    )
    fixture.session.add(passenger)
    await fixture.session.commit()
    return passenger


async def test_completed_submission_without_excel_contact_previews_and_sends_own_phone_once(group_update):
    passenger = await unmatched_completed(group_update)
    data = await preview(group_update, submission_status="submitted", document_status="pending")
    row = next(row for row in data["recipients"] if row["passenger_id"] == str(passenger.id))
    assert row["eligible"] and row["phone_number"] == passenger.client_phone
    assert row["phone_source"] == "submitted" and row["recipient_id"] is None
    # Preview never adds a broadcast contact or queues anything.
    assert len(list((await group_update.session.scalars(select(WhatsAppBroadcastRecipientModel))).all())) == 4
    payload = {**request_for(data), "audience_keys": [row["audience_key"]]}
    assert (await queue(group_update, payload)).json()["queued_count"] == 1
    await queue(group_update, payload)
    assert len(list((await group_update.session.scalars(select(WhatsAppBroadcastRecipientModel))).all())) == 5
    new_rows = (await preview(group_update))["recipients"]
    assert len([item for item in new_rows if item["phone_number"] == passenger.client_phone]) == 1
    batch = await group_update.session.scalar(select(WhatsAppMessageLogModel.batch_id))
    await document_update_runtime.run_document_update_broadcast(batch_id=str(batch))
    await document_update_runtime.run_document_update_broadcast(batch_id=str(batch))
    group_update.provider.assert_awaited_once()
    assert group_update.provider.await_args.kwargs["to_number"] == passenger.client_phone


async def test_unmatched_completed_submission_respects_document_filter_and_current_phone(group_update):
    passenger = await unmatched_completed(group_update)
    group_update.passengers.append(passenger)
    await document(group_update, 3, status="sent")
    pending = await preview(group_update, document_status="pending")
    assert str(passenger.id) not in {row["passenger_id"] for row in pending["recipients"]}
    sent = await preview(group_update, document_status="sent")
    payload = request_for(sent)
    await queue(group_update, payload)
    passenger.client_phone = "+919444555667"
    await group_update.session.commit()
    batch = await group_update.session.scalar(select(WhatsAppMessageLogModel.batch_id))
    await document_update_runtime.run_document_update_broadcast(batch_id=str(batch))
    group_update.provider.assert_not_awaited()
    assert await group_update.session.scalar(select(WhatsAppMessageLogModel.status)) == "skipped"


async def test_unmatched_completed_submission_without_valid_phone_is_visible_but_blocked(group_update):
    passenger = await unmatched_completed(group_update, phone=None)
    rows = (await preview(group_update, submission_status="submitted"))["recipients"]
    row = next(row for row in rows if row["passenger_id"] == str(passenger.id))
    assert not row["eligible"] and row["phone_number"] is None
    group_update.publish.assert_not_awaited()
