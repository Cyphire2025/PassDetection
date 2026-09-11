"""Staff broadcast access must not reveal unrelated passport-group records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import whatsapp
from app.presentation.dependencies.auth import get_current_active_user


@pytest.fixture
async def staff_broadcast(db_session: AsyncSession):
    now = datetime.now(tz=UTC)
    agency_id, staff_id = uuid.uuid4(), uuid.uuid4()
    staff = User(
        id=staff_id,
        agency_id=agency_id,
        email="staff@example.test",
        hashed_password="unused",
        full_name="Staff",
        role=UserRole.AGENCY_STAFF,
    )
    broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name="Shared broadcast",
        organizing_company_name="Agency",
        recipient_opt_in_confirmed_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all(
        [
            AgencyModel(id=agency_id, name="Agency", email="agency@example.test"),
            broadcast,
        ]
    )
    for index, name in enumerate(("Submitted passenger", "Missing passenger")):
        db_session.add(
            WhatsAppBroadcastRecipientModel(
                id=uuid.uuid4(),
                agency_id=agency_id,
                broadcast_group_id=broadcast.id,
                name=name,
                phone_number=f"987654321{index}",
                normalized_phone_number=f"+91987654321{index}",
                created_at=now,
            )
        )
    groups = {}
    for access in ("owned", "assigned", "hidden", "archived"):
        group = ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            token=str(uuid.uuid4()),
            name=access,
            status="archived" if access == "archived" else "active",
            created_by_user_id=staff_id if access in {"owned", "archived"} else uuid.uuid4(),
            departure_cities=[],
            created_at=now,
        )
        groups[access] = group
        db_session.add_all(
            [
                group,
                ClientGroupWhatsAppBroadcastLinkModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    client_group_id=group.id,
                    broadcast_group_id=broadcast.id,
                    created_at=now,
                ),
                PassportSubmissionModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    group_id=group.id,
                    client_name=f"Unidentified {access}",
                    client_phone="9000000000",
                    image_s3_key=f"{access}/passport.jpg",
                    status="submitted",
                    confirmed_fields={},
                    extracted_fields={},
                    created_at=now,
                    updated_at=now,
                ),
                PassportSubmissionModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    group_id=group.id,
                    client_name="Submitted passenger",
                    client_phone="9876543210",
                    image_s3_key=f"{access}/matched.jpg",
                    status="submitted",
                    confirmed_fields={},
                    extracted_fields={},
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        if access == "assigned":
            db_session.add(
                ManagerGroupAccessModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    manager_id=staff_id,
                    group_id=group.id,
                    created_at=now,
                )
            )
    await db_session.flush()
    app = FastAPI()
    app.include_router(whatsapp.router, prefix="/whatsapp")
    app.dependency_overrides[get_current_active_user] = lambda: staff
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, broadcast=broadcast, groups=groups)


@pytest.mark.asyncio
async def test_broadcast_detail_and_roster_preserve_staff_passport_group_scope(staff_broadcast):
    context = staff_broadcast
    path = f"/whatsapp/groups/{context.broadcast.id}"
    detail = await context.client.get(path)
    assert detail.status_code == 200, detail.text
    assert {group["name"] for group in detail.json()["linked_client_groups"]} == {
        "owned",
        "assigned",
    }

    roster = await context.client.get(f"{path}/recipient-roster")
    assert roster.status_code == 200, roster.text
    unidentified = [
        item["unidentified_upload"]
        for item in roster.json()["items"]
        if item["kind"] == "unidentified"
    ]
    assert {item["client_group_name"] for item in unidentified} == {"owned", "assigned"}
    assert roster.json()["counts"]["unidentified"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("access", ["owned", "assigned"])
async def test_staff_selected_reminder_scope_preserves_full_submission_matching(
    staff_broadcast, access
):
    context = staff_broadcast
    preview = await context.client.post(
        f"/whatsapp/groups/{context.broadcast.id}/preview",
        json={
            "message_type": "reminder",
            "audience": "not_submitted",
            "audience_client_group_id": str(context.groups[access].id),
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["audience_recipient_count"] == 1
    assert preview.json()["excluded_submitted_count"] == 1
    assert preview.json()["recipient_name"] == "Missing passenger"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["preview", "send"])
async def test_staff_reminder_requires_explicit_accessible_group(staff_broadcast, action):
    context = staff_broadcast
    path = f"/whatsapp/groups/{context.broadcast.id}/{action}"
    # Hidden linked groups still make the audience ambiguous. They cannot be
    # silently removed from the decision about which group supplies matching.
    ambiguous = await context.client.post(
        path,
        json={
            "message_type": "reminder",
            "audience": "not_submitted",
        },
    )
    assert ambiguous.status_code == 409, ambiguous.text
    forbidden = await context.client.post(
        path,
        json={
            "message_type": "reminder",
            "audience": "not_submitted",
            "audience_client_group_id": str(context.groups["hidden"].id),
        },
    )
    assert forbidden.status_code == 403, forbidden.text
