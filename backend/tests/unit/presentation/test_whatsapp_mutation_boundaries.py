"""Exercise broadcast mutations through HTTP with real tenant-scoped records."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import whatsapp_groups_manage, whatsapp_recipients
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.middleware.error_handler import register_exception_handlers


@pytest.fixture
async def broadcast_mutations(db_session):
    now = datetime(2020, 1, 1, tzinfo=UTC)
    agency_id, foreign_agency_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    user = User(
        id=user_id, agency_id=agency_id, email="admin@example.test",
        hashed_password="unused", full_name="Admin", role=UserRole.AGENCY_ADMIN,
    )
    db_session.add_all([
        AgencyModel(id=agency_id, name="Owned agency", email="owned@example.test"),
        AgencyModel(id=foreign_agency_id, name="Foreign agency", email="foreign@example.test"),
    ])
    await db_session.flush()
    db_session.add(UserModel(
        id=user_id, agency_id=agency_id, email=user.email, full_name=user.full_name,
        hashed_password="unused", role=user.role.value,
    ))
    groups, recipients, support = [], [], []
    for index, tenant_id in enumerate((agency_id, agency_id, foreign_agency_id)):
        group = WhatsAppBroadcastGroupModel(
            id=uuid.uuid4(), agency_id=tenant_id, name=f"Group {index}",
            organizing_company_name="Original company", recipient_opt_in_confirmed_at=now,
            created_at=now, updated_at=now,
        )
        groups.append(group)
        db_session.add(group)
        await db_session.flush()
        row = WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(), agency_id=tenant_id, broadcast_group_id=group.id,
            name=f"Recipient {index}", phone_number=f"990000000{index}",
            normalized_phone_number=f"+91990000000{index}",
            imported_fields={"email": f"recipient{index}@example.test"}, created_at=now,
        )
        contact = WhatsAppBroadcastSupportContactModel(
            id=uuid.uuid4(), agency_id=tenant_id, broadcast_group_id=group.id,
            name=f"Support {index}", phone_number=f"980000000{index}",
            normalized_phone_number=f"+91980000000{index}", sort_order=0, created_at=now,
        )
        recipients.append(row)
        support.append(contact)
        db_session.add_all([row, contact])
    await db_session.commit()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(whatsapp_groups_manage.router, prefix="/whatsapp")
    app.include_router(whatsapp_recipients.router, prefix="/whatsapp")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            client=client, session=db_session, user=user, groups=groups,
            recipients=recipients, support=support,
        )


async def _mutate(context, action, *, group_index=0, recipient_index=0):
    path = f"/whatsapp/groups/{context.groups[group_index].id}"
    if action == "group":
        return await context.client.patch(path, data={"name": "Updated"})
    path += f"/recipients/{context.recipients[recipient_index].id}"
    if action == "phone":
        return await context.client.patch(path, json={"phone_number": "9900000099"})
    return await context.client.delete(path)


@pytest.mark.parametrize("action", ["group", "phone", "remove"])
async def test_other_agency_cannot_mutate_broadcast(broadcast_mutations, action):
    context = broadcast_mutations
    response = await _mutate(context, action, group_index=2, recipient_index=2)
    assert response.status_code == 404, response.text
    assert context.groups[2].name == "Group 2"
    assert context.recipients[2].normalized_phone_number == "+919900000002"
    assert context.recipients[2].removed_at is None


@pytest.mark.parametrize("action", ["phone", "remove"])
@pytest.mark.parametrize("recipient_index", [1, 2])
async def test_recipient_must_belong_to_selected_group(broadcast_mutations, action, recipient_index):
    context = broadcast_mutations
    response = await _mutate(context, action, recipient_index=recipient_index)
    assert response.status_code == 404, response.text
    assert context.recipients[recipient_index].removed_at is None
    assert context.recipients[recipient_index].normalized_phone_number.endswith(str(recipient_index))


@pytest.mark.parametrize("action", ["group", "phone", "remove"])
async def test_client_manager_cannot_mutate_broadcast(broadcast_mutations, action):
    context = broadcast_mutations
    context.user.role = UserRole.CLIENT_MANAGER
    response = await _mutate(context, action)
    assert response.status_code == 403, response.text
    assert context.groups[0].name == "Group 0"
    assert context.recipients[0].removed_at is None
    assert context.recipients[0].normalized_phone_number == "+919900000000"


@pytest.mark.parametrize("action", ["group", "phone", "remove"])
async def test_archived_broadcast_rejects_mutations(broadcast_mutations, action):
    context = broadcast_mutations
    context.groups[0].archived_at = datetime.now(UTC)
    await context.session.flush()
    response = await _mutate(context, action)
    assert response.status_code == 409, response.text
    assert "archived" in response.text
    assert context.groups[0].name == "Group 0"
    assert context.recipients[0].normalized_phone_number == "+919900000000"
    assert context.recipients[0].removed_at is None


async def test_group_patch_replaces_only_its_support_contacts_in_order(broadcast_mutations):
    context = broadcast_mutations
    response = await context.client.patch(
        f"/whatsapp/groups/{context.groups[0].id}",
        data={
            "name": "  Updated group  ", "organizing_company_name": "  Updated company  ",
            "support_contacts_json": json.dumps([
                {"name": "  First  ", "phone_number": "+91 97000 00001"},
                {"name": "Duplicate first", "phone_number": "9700000001"},
                {"name": "Second", "phone_number": "9700000002"},
            ]),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Updated group"
    assert response.json()["organizing_company_name"] == "Updated company"
    contacts = list((await context.session.scalars(
        select(WhatsAppBroadcastSupportContactModel)
        .where(WhatsAppBroadcastSupportContactModel.broadcast_group_id == context.groups[0].id)
        .order_by(WhatsAppBroadcastSupportContactModel.sort_order)
    )).all())
    assert [(row.name, row.normalized_phone_number, row.sort_order) for row in contacts] == [
        ("First", "+919700000001", 0), ("Second", "+919700000002", 1),
    ]
    assert all(row.agency_id == context.user.agency_id for row in contacts)
    for index in (1, 2):
        await context.session.refresh(context.support[index])
        assert context.support[index].name == f"Support {index}"


@pytest.mark.parametrize("form", [
    {"name": "   "}, {"name": "x" * 101},
    {"organizing_company_name": "   "}, {"organizing_company_name": "x" * 101},
    {"support_contacts_json": "[]"},
    {"support_contacts_json": '[{"name":"Invalid","phone_number":"123"}]'},
])
async def test_invalid_group_patch_preserves_existing_values(broadcast_mutations, form):
    context = broadcast_mutations
    response = await context.client.patch(f"/whatsapp/groups/{context.groups[0].id}", data=form)
    assert response.status_code == 400, response.text
    assert context.groups[0].name == "Group 0"
    assert context.groups[0].organizing_company_name == "Original company"
    assert await context.session.get(WhatsAppBroadcastSupportContactModel, context.support[0].id)


@pytest.mark.parametrize("form", [
    {"contacts_json": "invalid-json"}, {"contacts_json": "[null]"},
    {"support_contacts_json": "invalid-json"}, {"support_contacts_json": "[]"},
])
async def test_invalid_creation_does_not_insert_broadcast(broadcast_mutations, form):
    context = broadcast_mutations
    response = await context.client.post("/whatsapp/groups", data={
        "name": "New group", "organizing_company_name": "Company",
        "recipient_opt_in_confirmed": "true",
        "support_contacts_json": '[{"name":"Support","phone_number":"9700000001"}]',
        **form,
    })
    assert response.status_code == 400, response.text
    groups = list((await context.session.scalars(select(WhatsAppBroadcastGroupModel))).all())
    assert len(groups) == 3


async def test_phone_change_invalidates_delivery_state_and_identical_phone_is_noop(
    broadcast_mutations, monkeypatch,
):
    context = broadcast_mutations
    group, row = context.groups[0], context.recipients[0]
    state = WhatsAppRecipientMessageStateModel(
        broadcast_group_id=group.id, agency_id=group.agency_id, recipient_id=row.id,
        message_type="reminder", status="delivered", batch_id=uuid.uuid4(),
        submitted_at=datetime.now(UTC), provider_status_at=datetime.now(UTC),
    )
    context.session.add(state)
    await context.session.flush()
    reconcile = AsyncMock(wraps=whatsapp_recipients.reconcile_mobile_passenger_access_for_broadcast)
    monkeypatch.setattr(whatsapp_recipients, "reconcile_mobile_passenger_access_for_broadcast", reconcile)
    response = await _mutate(context, "phone")
    assert response.status_code == 200, response.text
    assert row.normalized_phone_number == "+919900000099"
    assert row.imported_fields == {"email": "recipient0@example.test"}
    await context.session.refresh(state)
    assert state.status == "failed"
    assert state.batch_id is state.submitted_at is state.provider_status_at is None
    reconcile.assert_awaited_once_with(
        context.session, agency_id=group.agency_id, broadcast_group_id=group.id,
        actor_user_id=context.user.id,
    )
    updated_at = group.updated_at
    response = await _mutate(context, "phone")
    assert response.status_code == 200, response.text
    assert group.updated_at.replace(tzinfo=UTC) == updated_at.replace(tzinfo=UTC)
    assert reconcile.await_count == 1
    assert context.recipients[1].normalized_phone_number == "+919900000001"


@pytest.mark.parametrize("status", ["processing", "delivery_unknown"])
async def test_in_flight_or_uncertain_delivery_blocks_phone_change(broadcast_mutations, status):
    context = broadcast_mutations
    row = context.recipients[0]
    state = WhatsAppRecipientMessageStateModel(
        broadcast_group_id=row.broadcast_group_id, agency_id=row.agency_id, recipient_id=row.id,
        message_type="reminder", status=status,
    )
    context.session.add(state)
    await context.session.flush()
    response = await _mutate(context, "phone")
    assert response.status_code == 409, response.text
    assert row.normalized_phone_number == "+919900000000"
    await context.session.refresh(state)
    assert state.status == status


async def test_removal_fails_only_queued_messages_for_selected_recipient(broadcast_mutations):
    context = broadcast_mutations
    records = []
    for index, status in ((0, "queued"), (1, "queued"), (0, "delivered")):
        row = context.recipients[index]
        message_type = "reminder" if status == "queued" else "welcome"
        common = dict(
            broadcast_group_id=row.broadcast_group_id, agency_id=row.agency_id,
            recipient_id=row.id, message_type=message_type, status=status,
        )
        log = WhatsAppMessageLogModel(**common)
        state = WhatsAppRecipientMessageStateModel(**common, batch_id=uuid.uuid4())
        context.session.add_all([log, state])
        records.append((log, state))
    await context.session.flush()
    response = await _mutate(context, "remove")
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True}
    assert context.recipients[0].removed_at is not None
    assert context.recipients[1].removed_at is None
    for log, state in records:
        await context.session.refresh(log)
        await context.session.refresh(state)
    assert records[0][0].status == records[0][1].status == "failed"
    assert records[0][1].batch_id is None
    assert "Recipient removed" in records[0][0].error_message
    assert records[1][0].status == records[1][1].status == "queued"
    assert records[2][0].status == records[2][1].status == "delivered"
    response = await _mutate(context, "remove")
    assert response.status_code == 404
