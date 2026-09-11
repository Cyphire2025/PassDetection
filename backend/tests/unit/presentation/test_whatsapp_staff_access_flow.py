"""Exercise staff broadcast management and tracking through actual HTTP routes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import AgencyModel, UserModel, WhatsAppMessageLogModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import client_groups, whatsapp, whatsapp_activity
from app.presentation.dependencies.auth import get_current_active_user


@pytest.mark.asyncio
async def test_staff_can_manage_and_track_broadcasts_only_in_their_agency(
    db_session: AsyncSession,
) -> None:
    agency_id, other_agency_id, staff_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    staff = User(
        id=staff_id,
        email="staff@example.test",
        hashed_password="unused",
        full_name="Staff",
        role=UserRole.AGENCY_STAFF,
        agency_id=agency_id,
    )
    db_session.add_all(
        [
            AgencyModel(id=agency_id, name="Agency", email="agency@example.test"),
            AgencyModel(id=other_agency_id, name="Other", email="other@example.test"),
            UserModel(
                id=staff.id,
                agency_id=agency_id,
                email=staff.email,
                full_name=staff.full_name,
                hashed_password="unused",
                role=staff.role.value,
            ),
        ]
    )
    await db_session.commit()

    app = FastAPI()
    app.include_router(whatsapp.router, prefix="/whatsapp")
    app.include_router(whatsapp_activity.router, prefix="/whatsapp")
    app.include_router(client_groups.router, prefix="/upload-links")
    app.dependency_overrides[get_current_active_user] = lambda: staff
    app.dependency_overrides[get_db_session] = lambda: db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/whatsapp/groups",
            data={
                "name": "Staff list",
                "organizing_company_name": "Agency",
                "contacts_json": json.dumps([{"name": "Passenger", "phone_number": "9876543210"}]),
                "support_contacts_json": json.dumps(
                    [{"name": "Office", "phone_number": "9876543211"}]
                ),
                "recipient_opt_in_confirmed": "true",
            },
        )
        assert created.status_code == 201, created.text
        group_id = created.json()["id"]
        recipient_id = created.json()["recipients"][0]["id"]
        path = f"/whatsapp/groups/{group_id}"

        listed = await client.get("/whatsapp/groups")
        assert listed.status_code == 200
        assert [group["id"] for group in listed.json()] == [group_id]
        options = await client.get("/upload-links/whatsapp-broadcast-options")
        assert options.status_code == 200
        assert [group["id"] for group in options.json()] == [group_id]
        updated = await client.patch(path, data={"name": "Corrected staff list"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Corrected staff list"
        preview = await client.post(f"{path}/preview", json={"message_type": "reminder"})
        assert preview.status_code == 200, preview.text
        assert preview.json()["eligible_recipient_count"] == 1

        batch_id = uuid.uuid4()
        now = datetime.now(tz=UTC)
        db_session.add(
            WhatsAppMessageLogModel(
                batch_id=batch_id,
                broadcast_group_id=uuid.UUID(group_id),
                recipient_id=uuid.UUID(recipient_id),
                agency_id=agency_id,
                message_type="reminder",
                status="failed",
                error_message="Test delivery failure",
                status_updated_at=now,
                created_at=now,
            )
        )
        await db_session.flush()
        tracking_paths = [
            f"/whatsapp/batches/{batch_id}",
            f"/whatsapp/batches/{batch_id}/summary",
            f"/whatsapp/activities/broadcast/{batch_id}",
        ]
        for tracking_path in tracking_paths:
            tracked = await client.get(tracking_path)
            assert tracked.status_code == 200, tracked.text
            assert tracked.json()["failed"] == 1
        failures_path = f"/whatsapp/activities/broadcast/{batch_id}/failures"
        failures = await client.get(failures_path)
        assert failures.status_code == 200
        assert failures.json()[0]["recipient_name"] == "Passenger"

        staff.agency_id = other_agency_id
        assert (await client.get("/whatsapp/groups")).json() == []
        assert (await client.get("/upload-links/whatsapp-broadcast-options")).json() == []
        for read_path in [path, *tracking_paths]:
            assert (await client.get(read_path)).status_code == 404
        assert (await client.get(failures_path)).json() == []
        assert (await client.patch(path, data={"name": "Forbidden"})).status_code == 404
        for action in ("preview", "send"):
            rejected = await client.post(f"{path}/{action}", json={"message_type": "reminder"})
            assert rejected.status_code == 404, rejected.text
        assert (await client.delete(path)).status_code == 404

        staff.agency_id = agency_id
        persisted = await client.get(path)
        assert persisted.status_code == 200
        assert persisted.json()["name"] == "Corrected staff list"
        deleted = await client.delete(path)
        assert deleted.status_code == 200, deleted.text
        assert (await client.get(path)).status_code == 404
