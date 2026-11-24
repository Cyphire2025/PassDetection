"""Real persisted activity filters, counts and group visibility without sends."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DocumentWhatsAppDeliveryModel,
    ManagerGroupAccessModel,
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes import whatsapp_activity as activity
from app.presentation.api.v1.schemas.whatsapp_activity_schemas import DocumentActivityStatusFilter


@dataclass
class DocumentActivityFixture:
    actor: User
    group: ClientGroupModel
    batch_id: uuid.UUID
    deliveries: list[DocumentWhatsAppDeliveryModel]


@pytest.fixture
async def document_activity(db_session: AsyncSession) -> DocumentActivityFixture:
    agency_id, actor_id = uuid.uuid4(), uuid.uuid4()
    actor = User(id=actor_id, email="activity@example.test", hashed_password="unused",
                 full_name="Activity operator", role=UserRole.AGENCY_ADMIN, agency_id=agency_id)
    db_session.add(AgencyModel(id=agency_id, name="Activity agency", email="agency@example.test"))
    await db_session.flush()
    db_session.add(UserModel(id=actor_id, agency_id=agency_id, email=actor.email,
                             hashed_password="unused", full_name=actor.full_name,
                             role=actor.role.value))
    await db_session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency_id, name="Activity trip",
                             token=uuid.uuid4().hex)
    db_session.add(group)
    await db_session.flush()
    batch_id = uuid.uuid4()
    now = datetime.now(UTC)
    states = ["queued", "processing", "queued", "processing", "submitted", "sent",
              "delivered", "read", "delivery_unknown", "stalled", "failed", "provider_declined"]
    deliveries = [DocumentWhatsAppDeliveryModel(
        id=uuid.UUID(int=index + 1), agency_id=agency_id, group_id=group.id,
        send_batch_id=batch_id, document_type="visa", document_filename=f"document-{index}.pdf",
        passenger_name=f"Person {index:02}", phone_number=f"+9191234567{index:02}",
        normalized_phone_number=f"+9191234567{index:02}", template_name="synthetic_v1",
        template_parameter_values=[], status=state, status_updated_at=(
            now - timedelta(hours=1) if index in {2, 3} else now
        ), created_at=now, updated_at=now,
    ) for index, state in enumerate(states)]
    db_session.add_all(deliveries)
    await db_session.commit()
    return DocumentActivityFixture(actor, group, batch_id, deliveries)


@pytest.mark.parametrize(("status_filter", "indices"), [
    ("all", list(range(12))), ("queued", [0]), ("processing", [1]),
    ("sent", [4, 5, 6, 7]), ("delivered", [6, 7]), ("read", [7]),
    ("failed", [10, 11]), ("needs_review", [2, 3, 8, 9]),
])
async def test_document_page_matches_summary_status_semantics(
    db_session: AsyncSession, document_activity: DocumentActivityFixture,
    status_filter: DocumentActivityStatusFilter, indices: list[int],
) -> None:
    fixture = document_activity
    page = await activity.get_document_activity_deliveries(
        fixture.batch_id, status_filter=status_filter, q="", offset=0, limit=100,
        current_user=fixture.actor, session=db_session,
    )
    assert page.total == len(indices)
    assert [item.delivery_id for item in page.items] == [fixture.deliveries[i].id for i in indices]
    assert [item.status for item in page.items] == [
        "stalled" if i in {2, 3} else fixture.deliveries[i].status for i in indices
    ]
    summary = await activity.get_whatsapp_activity_summary(
        "document", fixture.batch_id, current_user=fixture.actor, session=db_session,
    )
    assert (summary.total, summary.queued, summary.sent, summary.failed, summary.delivery_unknown) == (
        12, 2, 4, 2, 4,
    )
    assert summary.status_counts == {"queued": 1, "processing": 1, "submitted": 1, "sent": 1,
                                    "delivered": 1, "read": 1, "failed": 2,
                                    "delivery_unknown": 1, "stalled": 3}
    failures = await activity.get_whatsapp_activity_failures(
        "document", fixture.batch_id, current_user=fixture.actor, session=db_session,
    )
    assert [item.recipient_name for item in failures] == ["Person 10", "Person 11"]
    assert not db_session.new and not db_session.dirty


async def test_document_search_escapes_literal_wildcards_and_keeps_page_totals(
    db_session: AsyncSession, document_activity: DocumentActivityFixture,
) -> None:
    fixture = document_activity
    fixture.deliveries[0].document_filename = r"Visa_100%\final.pdf"
    await db_session.commit()
    literal = await activity.get_document_activity_deliveries(
        fixture.batch_id, status_filter="all", q=r"  _100%\final  ", offset=0, limit=1,
        current_user=fixture.actor, session=db_session,
    )
    assert literal.total == 1
    assert [item.delivery_id for item in literal.items] == [fixture.deliveries[0].id]
    phone = await activity.get_document_activity_deliveries(
        fixture.batch_id, status_filter="all", q="+919123456711", offset=0, limit=10,
        current_user=fixture.actor, session=db_session,
    )
    assert [item.delivery_id for item in phone.items] == [fixture.deliveries[11].id]
    page = await activity.get_document_activity_deliveries(
        fixture.batch_id, status_filter="all", q="person", offset=3, limit=2,
        current_user=fixture.actor, session=db_session,
    )
    assert (page.total, page.offset, page.limit) == (12, 3, 2)
    assert [item.delivery_id for item in page.items] == [fixture.deliveries[i].id for i in (3, 4)]
    empty = await activity.get_document_activity_deliveries(
        fixture.batch_id, status_filter="failed", q="no match", offset=0, limit=10,
        current_user=fixture.actor, session=db_session,
    )
    assert empty.total == 0 and empty.items == []
    beyond = await activity.get_document_activity_deliveries(
        fixture.batch_id, status_filter="all", q="", offset=20, limit=10,
        current_user=fixture.actor, session=db_session,
    )
    assert beyond.total == 12 and beyond.items == []


@pytest.mark.parametrize("access", ["foreign_agency", "unassigned_staff", "archived_staff", "deleted"])
async def test_document_batch_visibility_is_checked_before_filters(
    db_session: AsyncSession, document_activity: DocumentActivityFixture, access: str,
) -> None:
    fixture = document_activity
    if access == "foreign_agency":
        fixture.actor.agency_id = uuid.uuid4()
    elif access == "unassigned_staff":
        fixture.actor.role = UserRole.AGENCY_STAFF
    elif access == "archived_staff":
        fixture.actor.role = UserRole.AGENCY_STAFF
        fixture.group.created_by_user_id = fixture.actor.id
        fixture.group.status = "archived"
    else:
        fixture.group.deleted_at = datetime.now(UTC)
    await db_session.commit()
    with pytest.raises(HTTPException) as page_error:
        await activity.get_document_activity_deliveries(
            fixture.batch_id, status_filter="failed", q="no match", offset=100, limit=1,
            current_user=fixture.actor, session=db_session,
        )
    assert page_error.value.status_code == 404
    with pytest.raises(HTTPException) as summary_error:
        await activity.get_whatsapp_activity_summary(
            "document", fixture.batch_id, current_user=fixture.actor, session=db_session,
        )
    assert summary_error.value.status_code == 404
    assert await activity.get_whatsapp_activity_failures(
        "document", fixture.batch_id, current_user=fixture.actor, session=db_session,
    ) == []


@pytest.mark.parametrize("access", ["creator", "assigned", "archived_admin", "retained_superadmin"])
async def test_document_activity_keeps_role_specific_group_access(
    db_session: AsyncSession, document_activity: DocumentActivityFixture, access: str,
) -> None:
    fixture = document_activity
    if access in {"creator", "assigned"}:
        fixture.actor.role = UserRole.AGENCY_STAFF
        if access == "creator":
            fixture.group.created_by_user_id = fixture.actor.id
        else:
            db_session.add(ManagerGroupAccessModel(manager_id=fixture.actor.id,
                                                   group_id=fixture.group.id,
                                                   agency_id=fixture.group.agency_id))
    elif access == "archived_admin":
        fixture.group.status = "archived"
    else:
        fixture.group.deleted_at = datetime.now(UTC)
        fixture.actor.role = UserRole.SUPER_ADMIN
        fixture.actor.agency_id = None
    await db_session.commit()
    page = await activity.get_document_activity_deliveries(
        fixture.batch_id, status_filter="all", q="", offset=0, limit=100,
        current_user=fixture.actor, session=db_session,
    )
    assert page.total == 12 and len(page.items) == 12


async def test_missing_document_batch_does_not_look_like_an_empty_filter(
    db_session: AsyncSession, document_activity: DocumentActivityFixture,
) -> None:
    with pytest.raises(HTTPException) as error:
        await activity.get_document_activity_deliveries(
            uuid.uuid4(), status_filter="all", q="", offset=0, limit=1,
            current_user=document_activity.actor, session=db_session,
        )
    assert error.value.status_code == 404


@pytest.mark.parametrize("kind", ["broadcast", "qr"])
async def test_other_activity_engines_use_saved_destinations_and_authorized_batches(
    db_session: AsyncSession, document_activity: DocumentActivityFixture, kind: str,
) -> None:
    fixture = document_activity
    agency_id = fixture.group.agency_id
    now = datetime.now(UTC)
    batch_id = uuid.uuid4()
    if kind == "broadcast":
        group = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency_id, name="Broadcast")
        db_session.add(group)
        await db_session.flush()
        recipient = WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(), agency_id=agency_id, broadcast_group_id=group.id, name="Recipient",
            phone_number="+919000000000", normalized_phone_number="+919000000000",
        )
        db_session.add(recipient)
        await db_session.flush()
        db_session.add(WhatsAppMessageLogModel(
            agency_id=agency_id, broadcast_group_id=group.id, recipient_id=recipient.id,
            batch_id=batch_id, message_type="welcome", status="failed",
            normalized_phone_number="+919111111111", error_message="Synthetic failure",
            status_updated_at=now, created_at=now,
        ))
        title, name = "Welcome message broadcast", "Recipient"
    else:
        passenger = PassportSubmissionModel(
            id=uuid.uuid4(), agency_id=agency_id, group_id=fixture.group.id,
            client_name="QR passenger", image_s3_key="synthetic/passport",
        )
        db_session.add(passenger)
        await db_session.flush()
        token = PassengerQRTokenModel(
            id=uuid.uuid4(), agency_id=agency_id, passenger_id=passenger.id,
            token_hash=uuid.uuid4().hex, expires_at=now + timedelta(days=1),
        )
        db_session.add(token)
        await db_session.flush()
        db_session.add(PassengerQrWhatsAppDeliveryModel(
            agency_id=agency_id, group_id=fixture.group.id, passenger_id=passenger.id,
            qr_token_id=token.id, send_batch_id=batch_id, passenger_name="QR passenger",
            phone_number="+919111111111", normalized_phone_number="+919111111111",
            template_name="synthetic_v1", template_parameter_values=[], status="failed",
            error_message="Synthetic failure", status_updated_at=now, created_at=now, updated_at=now,
        ))
        title, name = "QR code broadcast", "QR passenger"
    await db_session.commit()
    summary = await activity.get_whatsapp_activity_summary(
        kind, batch_id, current_user=fixture.actor, session=db_session,  # type: ignore[arg-type]
    )
    assert summary.title == title
    assert (summary.total, summary.failed) == (1, 1)
    failures = await activity.get_whatsapp_activity_failures(
        kind, batch_id, current_user=fixture.actor, session=db_session,  # type: ignore[arg-type]
    )
    assert [row.model_dump() for row in failures] == [{
        "recipient_name": name, "phone_number": "+919111111111", "error_message": "Synthetic failure",
    }]
    fixture.actor.agency_id = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        await activity.get_whatsapp_activity_summary(
            kind, batch_id, current_user=fixture.actor, session=db_session,  # type: ignore[arg-type]
        )
    assert error.value.status_code == 404
    assert await activity.get_whatsapp_activity_failures(
        kind, batch_id, current_user=fixture.actor, session=db_session,  # type: ignore[arg-type]
    ) == []
