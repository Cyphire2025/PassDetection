"""Source roster changes retain travellers but send to each unique phone once."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel as Link,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as Recipient,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastSourceContactModel as Contact,
)
from app.infrastructure.whatsapp import source_group_sync as sync


@pytest.fixture
async def roster(db_session):
    agency_id, group_id, broadcast_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    group = ClientGroupModel(
        id=group_id, agency_id=agency_id, token=str(uuid.uuid4()), name="Trip",
        status="active", import_only=True,
    )
    db_session.add_all([
        AgencyModel(id=agency_id, name="Agency", email="agency@example.test"), group,
        WhatsAppBroadcastGroupModel(id=broadcast_id, agency_id=agency_id, name="Broadcast"),
        Link(agency_id=agency_id, client_group_id=group_id, broadcast_group_id=broadcast_id),
    ])
    await db_session.commit()
    return db_session, agency_id, group, broadcast_id


def passenger(agency_id, group_id, phone="9876543210", name="Ada"):
    return PassportSubmissionModel(
        id=uuid.uuid4(), agency_id=agency_id, group_id=group_id, client_name=name,
        status="staff_approved", image_s3_key="excel-imports/source",
        confirmed_fields={"given_names": name, "surname": "Test"},
        staff_metadata={"upload_phone": phone}, client_reviewed_at=datetime.now(tz=UTC),
    )


async def run(roster, **kwargs):
    session, agency_id, group, _ = roster
    result = await sync.sync_group_broadcast_contacts(
        session, agency_id=agency_id, group_id=group.id, **kwargs,
    )
    await session.flush()
    return result


@pytest.mark.asyncio
async def test_shared_invalid_and_missing_numbers_are_kept_and_idempotent(roster):
    session, agency_id, group, _ = roster
    session.add_all([
        passenger(agency_id, group.id), passenger(agency_id, group.id, name="Grace"),
        passenger(agency_id, group.id, phone="bad", name="Invalid"),
        passenger(agency_id, group.id, phone="", name="Missing"),
    ])
    first = await run(roster)
    contacts = list((await session.scalars(select(Contact))).all())
    recipients = list((await session.scalars(select(Recipient))).all())
    assert len(contacts) == 4
    assert len(recipients) == 1
    assert len([row for row in contacts if row.recipient_id == recipients[0].id]) == 2
    assert recipients[0].is_source_managed
    assert first["added"] == 1
    timestamps = {row.id: row.updated_at for row in contacts}
    assert (await run(roster))["updated"] == 0
    assert {row.id: row.updated_at for row in contacts} == timestamps


@pytest.mark.asyncio
async def test_manual_contact_ownership_and_multiple_sources_survive_unlink(roster):
    session, agency_id, group, broadcast_id = roster
    manual = Recipient(
        agency_id=agency_id, broadcast_group_id=broadcast_id, name="Manual name",
        phone_number="9876543210", normalized_phone_number="+919876543210",
        imported_fields={"memo": "Manual"},
    )
    second = ClientGroupModel(
        id=uuid.uuid4(), agency_id=agency_id, name="Second", token=str(uuid.uuid4()),
        status="active", import_only=True,
    )
    session.add_all([
        manual, second, passenger(agency_id, group.id),
        passenger(agency_id, group.id, phone="9123456789"),
        passenger(agency_id, second.id, phone="9123456789"),
        Link(agency_id=agency_id, client_group_id=second.id, broadcast_group_id=broadcast_id),
    ])
    await run(roster)
    await sync.sync_group_broadcast_contacts(session, agency_id=agency_id, group_id=second.id)
    managed = await session.scalar(select(Recipient).where(Recipient.is_source_managed.is_(True)))
    assert manual.name == "Manual name" and manual.imported_fields == {"memo": "Manual"}
    assert not manual.is_source_managed
    # A shared phone's representative must not change when sources sync in a
    # different order: harmless edits should never cancel private deliveries.
    stable_name = managed.name
    assert (await run(roster))["updated"] == 0
    assert managed.name == stable_name
    await session.execute(delete(Link).where(Link.client_group_id == group.id))
    await run(roster, affected_broadcast_ids=[broadcast_id])
    assert manual.removed_at is None and managed.removed_at is None
    await session.execute(delete(Link).where(Link.client_group_id == second.id))
    await sync.sync_group_broadcast_contacts(
        session, agency_id=agency_id, group_id=second.id, affected_broadcast_ids=[broadcast_id],
    )
    assert manual.removed_at is None
    assert managed.removed_at is not None
    assert not list((await session.scalars(select(Contact))).all())
    assert len(list((await session.scalars(select(Recipient))).all())) == 2


@pytest.mark.asyncio
async def test_capacity_retains_overflow_and_reconsiders_it_after_removal(roster, monkeypatch):
    session, agency_id, group, _ = roster
    monkeypatch.setattr(sync, "MAX_WHATSAPP_RECIPIENTS", 1)
    first = passenger(agency_id, group.id)
    second = passenger(agency_id, group.id, phone="9123456789", name="Second")
    session.add_all([first, second])
    await run(roster)
    contacts = list((await session.scalars(select(Contact).order_by(Contact.name))).all())
    assert len(contacts) == 2
    overflow = next(row for row in contacts if row.issue == "recipient_limit")
    accepted = next(row for row in contacts if row.issue is None)
    assert overflow.recipient_id is None
    await session.execute(delete(PassportSubmissionModel).where(
        PassportSubmissionModel.id == accepted.source_submission_id,
    ))
    await run(roster)
    assert overflow.issue is None and overflow.recipient_id is not None
    active = list((await session.scalars(select(Recipient).where(Recipient.removed_at.is_(None)))).all())
    assert len(active) == 1
    assert active[0].id == overflow.recipient_id


def delivery(agency_id, group_id, broadcast_id, status):
    return DocumentWhatsAppDeliveryModel(
        agency_id=agency_id, group_id=group_id, broadcast_group_id=broadcast_id,
        send_batch_id=uuid.uuid4(), document_type="ticket", document_filename="ticket.pdf",
        passenger_name="Ada", phone_number="9876543210", normalized_phone_number="+919876543210",
        template_name="ticket", status=status,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["processing", "delivery_unknown"])
async def test_private_delivery_blocks_mutation_but_not_unchanged_sync(roster, status):
    session, agency_id, group, broadcast_id = roster
    person = passenger(agency_id, group.id)
    session.add(person)
    await run(roster)
    session.add(delivery(agency_id, group.id, broadcast_id, status))
    await session.commit()
    assert (await run(roster))["updated"] == 0
    person.staff_metadata = {"upload_phone": "9123456789"}
    with pytest.raises(ConflictError) as exc:
        await run(roster)
    assert exc.value.code == "WHATSAPP_SOURCE_SYNC_DELIVERY_ACTIVE"
    recipient = await session.scalar(select(Recipient))
    assert recipient.normalized_phone_number == "+919876543210"
    assert recipient.removed_at is None


@pytest.mark.asyncio
async def test_queued_private_delivery_is_cancelled_when_source_phone_changes(roster):
    session, agency_id, group, broadcast_id = roster
    person = passenger(agency_id, group.id)
    session.add(person)
    await run(roster)
    old = await session.scalar(select(Recipient))
    queued = delivery(agency_id, group.id, broadcast_id, "queued")
    session.add(queued)
    person.staff_metadata = {"upload_phone": "9123456789"}
    await run(roster)
    assert queued.status == "failed"
    assert old.removed_at is not None
    assert len(list((await session.scalars(select(Recipient))).all())) == 2


@pytest.mark.asyncio
async def test_tenant_boundaries_drafts_and_deleted_source(roster):
    session, agency_id, group, broadcast_id = roster
    session.add(passenger(agency_id, group.id))
    draft = passenger(agency_id, group.id, phone="9123456789")
    draft.status = "uploaded"
    session.add(draft)
    await run(roster)
    assert len(list((await session.scalars(select(Contact))).all())) == 1
    assert (await sync.sync_group_broadcast_contacts(
        session, agency_id=uuid.uuid4(), group_id=group.id, affected_broadcast_ids=[broadcast_id],
    ))["broadcasts"] == 0
    group.deleted_at = datetime.now(tz=UTC)
    await session.execute(delete(Link).where(Link.client_group_id == group.id))
    # This emulates FK cascades removing snapshots before a delete hook runs.
    await session.execute(delete(Contact).where(Contact.source_group_id == group.id))
    await run(roster, affected_broadcast_ids=[broadcast_id])
    recipient = await session.scalar(select(Recipient))
    assert recipient.removed_at is not None


@pytest.mark.asyncio
async def test_backfill_populates_existing_links_and_is_repeatable(roster, monkeypatch, capsys):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.whatsapp import source_group_backfill

    session, agency_id, group, _ = roster
    session.add(passenger(agency_id, group.id))
    await session.commit()
    monkeypatch.setattr(
        source_group_backfill, "AsyncSessionFactory",
        async_sessionmaker(session.bind, expire_on_commit=False),
    )
    assert await source_group_backfill.backfill() == 0
    assert await source_group_backfill.backfill() == 0
    assert len(list((await session.scalars(select(Contact))).all())) == 1
    assert len(list((await session.scalars(select(Recipient))).all())) == 1
    assert "9876543210" not in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("new_phone", ["9123456789", None])
async def test_staff_http_phone_edit_or_clear_updates_imported_source_and_broadcast(roster, new_phone):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
    from app.domain.entities.entities import User, UserRole
    from app.infrastructure.database.models import UserModel
    from app.infrastructure.database.session import get_db_session
    from app.presentation.api.v1.routes.passport_routes import client_details
    from app.presentation.dependencies.auth import get_current_active_user

    session, agency_id, group, _ = roster
    person = passenger(agency_id, group.id)
    session.add(person)
    actor = User(uuid.uuid4(), "staff@example.test", "unused", "Staff", UserRole.SUPER_ADMIN, None)
    session.add(UserModel(
        id=actor.id, email=actor.email, full_name=actor.full_name,
        hashed_password="unused", role=actor.role.value,
    ))
    await run(roster)
    old_recipient = await session.scalar(select(Recipient))
    await session.commit()
    app = FastAPI()
    app.include_router(client_details.router, prefix="/passports")

    async def database():
        yield session

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_current_active_user] = lambda: actor
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url = f"/passports/{person.id}/client-details"
        editor = (await client.get(url)).json()
        phone_field = next(field for field in editor["fields"] if field["key"] == "client_phone")
        assert phone_field["value"] == "9876543210"
        version = editor["updated_at"]
        if not version.endswith("Z") and "+" not in version:
            version += "Z"
        response = await client.patch(url, json={
            "expected_updated_at": version, "client_phone": new_phone,
        })
        assert response.status_code == 200, response.text
    await session.refresh(person)
    assert person.staff_metadata["upload_phone"] == ("+919123456789" if new_phone else "")
    assert authoritative_submission_phone(person) is None
    assert old_recipient.removed_at is not None
    contact = await session.scalar(select(Contact))
    assert contact.raw_phone_number == ("+919123456789" if new_phone else "")
    active = list((await session.scalars(select(Recipient).where(Recipient.removed_at.is_(None)))).all())
    assert [recipient.normalized_phone_number for recipient in active] == (
        ["+919123456789"] if new_phone else []
    )
