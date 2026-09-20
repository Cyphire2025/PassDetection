"""Creation uses scoped server data and never promotes imported numbers to OTP authority."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import func, select

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.application.use_cases.whatsapp.source_group_contacts import build_source_contacts
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    ManagerGroupAccessModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.imports.passport_excel_importer import PassportExcelImporter
from app.infrastructure.whatsapp.private_delivery_policy import PrivateDeliveryMutationBlocked
from app.presentation.api.v1.routes import whatsapp_source_groups as routes
from app.presentation.dependencies.auth import get_current_active_user


def _submission(**overrides):
    return SimpleNamespace(**{
        "status": "submitted", "client_phone": None,
        "client_reviewed_at": datetime.now(tz=UTC),
        "confirmed_fields": {"given_names": "Ada", "surname": "Lovelace"},
        "extracted_fields": {}, "staff_metadata": {"verified_whatsapp_numbers": "9876543210"},
        "image_s3_key": "excel-imports/source", "confidence_score": {"source": "excel_import"},
        **overrides,
    })


def test_imported_verified_column_round_trips_without_granting_phone_authority():
    workbook = Workbook()
    workbook.active.append(["GIVEN NAME", "SURNAME", "Verified WhatsApp Number", "Mobile Number"])
    workbook.active.append(["Ada", "Lovelace", "9876543210", "9123456789"])
    output = io.BytesIO()
    workbook.save(output)
    row = PassportExcelImporter().import_rows(output.getvalue())[0]
    submission = _submission(
        confirmed_fields=row.confirmed_fields, staff_metadata=row.staff_metadata,
        client_phone=row.client_phone,
    )
    preview = build_source_contacts(uuid.uuid4(), "Imported trip", [submission])
    assert preview["recipients"][0]["name"] == "Ada Lovelace"
    assert preview["recipients"][0]["phone_number"] == "+919876543210"
    assert authoritative_submission_phone(submission) is None
    assert row.client_phone == "9123456789"


def test_public_contact_wins_and_legacy_verified_column_is_supported():
    public = _submission(
        client_phone="9123456789", image_s3_key="uploads/passport.jpg", confidence_score={},
    )
    legacy = _submission(staff_metadata={"Verified WhatsApp Numbers": "9876543210"})
    preview = build_source_contacts(uuid.uuid4(), "Trip", [public, legacy])
    assert [row["phone_number"] for row in preview["recipients"]] == ["+919123456789", "+919876543210"]


def test_exclusion_counts_and_no_generic_phone_or_uploader_name_fallback():
    rows = [
        _submission(),
        _submission(staff_metadata={"verified_whatsapp_numbers": "+91 98765 43210"}),
        _submission(staff_metadata={}),
        _submission(staff_metadata={}, client_phone="9123456789"),
        _submission(staff_metadata={"verified_whatsapp_number": "not a phone"}),
        _submission(confirmed_fields={}, client_name="Uploader"),
        _submission(confirmed_fields={"given_names": "a" * 101}),
    ]
    preview = build_source_contacts(uuid.uuid4(), "Trip", rows)
    assert preview["recipient_count"] == 1
    assert preview["excluded_count"] == 6
    assert all(value == 1 for value in preview["excluded_counts"].values())


@pytest.mark.parametrize("phone", [None, "invalid"])
def test_invalid_or_removed_public_contact_cannot_revive_old_imported_phone(phone):
    public = _submission(
        client_phone=phone, image_s3_key="uploads/passport.jpg", confidence_score={},
    )
    preview = build_source_contacts(uuid.uuid4(), "Trip", [public])
    assert preview["recipient_count"] == 0
    assert preview["excluded_counts"]["invalid_phone" if phone else "missing_phone"] == 1


def test_conflicting_duplicate_verified_columns_fail_closed():
    row = _submission(staff_metadata={
        "verified_whatsapp_numbers": "9876543210",
        "verified_whatsapp_numbers_2": "9123456789",
    })
    preview = build_source_contacts(uuid.uuid4(), "Trip", [row])
    assert preview["recipient_count"] == 0
    assert preview["excluded_counts"]["invalid_phone"] == 1


@pytest.fixture
async def source_api(db_session, monkeypatch):
    now = datetime.now(tz=UTC)
    agency_id, other_agency_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    user = User(
        id=user_id, agency_id=agency_id, email="staff@test.example", hashed_password="unused",
        full_name="Staff", role=UserRole.AGENCY_STAFF,
    )
    db_session.add_all([
        AgencyModel(id=agency_id, name="Agency", email="agency@test.example"),
        AgencyModel(id=other_agency_id, name="Other", email="other@test.example"),
        UserModel(id=user_id, agency_id=agency_id, email=user.email, hashed_password="unused",
                  full_name="Staff", role=user.role.value, is_active=True),
    ])
    groups = {}
    for kind in ("owned", "assigned", "hidden", "archived", "deleted", "cross-agency"):
        group_id = uuid.uuid4()
        groups[kind] = group_id
        db_session.add(ClientGroupModel(
            id=group_id, agency_id=other_agency_id if kind == "cross-agency" else agency_id,
            token=str(uuid.uuid4()), name=kind, import_only=True,
            status="archived" if kind == "archived" else "active",
            deleted_at=now if kind == "deleted" else None,
            created_by_user_id=user_id if kind != "hidden" and kind != "assigned" else uuid.uuid4(),
        ))
        if kind == "assigned":
            db_session.add(ManagerGroupAccessModel(
                id=uuid.uuid4(), agency_id=agency_id, manager_id=user_id, group_id=group_id,
            ))
    submission_id = uuid.uuid4()
    db_session.add(PassportSubmissionModel(
        id=submission_id, agency_id=agency_id, group_id=groups["owned"], client_name="Uploader",
        client_phone="9123456789", client_reviewed_at=now, status="submitted",
        image_s3_key="excel-imports/test", confirmed_fields={"given_names": "Ada", "surname": "Lovelace"},
        staff_metadata={"verified_whatsapp_numbers": "9876543210"},
    ))
    await db_session.commit()
    app = FastAPI()
    app.include_router(routes.router, prefix="/whatsapp")
    app.dependency_overrides[get_current_active_user] = lambda: user

    async def override_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_session
    monkeypatch.setattr(routes, "reconcile_mobile_passenger_access_for_group", AsyncMock())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, db_session, groups, agency_id, submission_id


@pytest.mark.asyncio
async def test_sources_enforce_tenant_active_and_staff_assignment(source_api):
    client, _, groups, _, _ = source_api
    response = await client.get("/whatsapp/source-groups")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {str(groups["owned"]), str(groups["assigned"])}
    for kind in ("hidden", "archived", "deleted", "cross-agency"):
        response = await client.get(f"/whatsapp/source-groups/{groups[kind]}/preview")
        assert response.status_code == 404


async def _body(client, group_id):
    preview = (await client.get(f"/whatsapp/source-groups/{group_id}/preview")).json()
    return {
        "source_group_id": str(group_id), "name": "New broadcast", "organizing_company_name": "Company",
        "support_contacts": [{"name": "Support", "phone_number": "9000000000"}],
        "recipient_opt_in_confirmed": True, "preview_revision": preview["preview_revision"],
    }


@pytest.mark.asyncio
async def test_creation_uses_server_roster_and_appends_existing_link(source_api):
    client, session, groups, agency_id, _ = source_api
    existing_id = uuid.uuid4()
    session.add_all([
        WhatsAppBroadcastGroupModel(id=existing_id, agency_id=agency_id, name="Existing", organizing_company_name=""),
        ClientGroupWhatsAppBroadcastLinkModel(
            agency_id=agency_id, client_group_id=groups["owned"], broadcast_group_id=existing_id,
            matching_field_keys=["name"],
        ),
    ])
    await session.commit()
    response = await client.post("/whatsapp/groups/from-client-group", json=await _body(client, groups["owned"]))
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["group"]["recipient_count"] == 1
    assert data["group"]["recipients"][0]["phone_number"] == "+919876543210"
    assert data["group"]["recipients"][0]["name"] == "Ada Lovelace"
    assert data["group"]["linked_client_groups"][0]["id"] == str(groups["owned"])
    links = (await session.execute(select(ClientGroupWhatsAppBroadcastLinkModel))).scalars().all()
    assert len(links) == 2
    assert next(link for link in links if link.broadcast_group_id == existing_id).matching_field_keys == ["name"]


@pytest.mark.asyncio
async def test_creation_rejects_changed_preview_and_deactivated_group(source_api):
    client, session, groups, _, submission_id = source_api
    body = await _body(client, groups["owned"])
    row = await session.get(PassportSubmissionModel, submission_id)
    row.staff_metadata = {"verified_whatsapp_numbers": "9876543211"}
    await session.commit()
    response = await client.post("/whatsapp/groups/from-client-group", json=body)
    assert response.status_code == 409
    assert await session.scalar(select(func.count(WhatsAppBroadcastGroupModel.id))) == 0
    await session.rollback()
    group = await session.get(ClientGroupModel, groups["owned"])
    group.status = "archived"
    await session.commit()
    assert (await client.post("/whatsapp/groups/from-client-group", json=body)).status_code == 404


@pytest.mark.asyncio
async def test_create_requires_opt_in_and_refuses_browser_recipient_override(source_api):
    client, session, groups, _, _ = source_api
    body = await _body(client, groups["owned"])
    assert (await client.post("/whatsapp/groups/from-client-group", json={**body, "recipient_opt_in_confirmed": False})).status_code == 400
    assert (await client.post("/whatsapp/groups/from-client-group", json={**body, "recipients": []})).status_code == 422
    assert await session.scalar(select(func.count(WhatsAppBroadcastRecipientModel.id))) == 0


@pytest.mark.asyncio
async def test_create_blocks_active_private_delivery(source_api, monkeypatch):
    client, session, groups, _, _ = source_api
    monkeypatch.setattr(routes, "prepare_private_delivery_identity_mutation", AsyncMock(side_effect=PrivateDeliveryMutationBlocked("Delivery in progress")))
    response = await client.post("/whatsapp/groups/from-client-group", json=await _body(client, groups["owned"]))
    assert response.status_code == 409
    assert await session.scalar(select(func.count(WhatsAppBroadcastGroupModel.id))) == 0


@pytest.mark.asyncio
async def test_preview_excludes_drafts_and_rejected_operational_passengers(source_api):
    client, session, groups, agency_id, submission_id = source_api
    session.add(PassportSubmissionModel(
        agency_id=agency_id, group_id=groups["owned"], client_name="Draft", status="uploaded",
        image_s3_key="uploads/draft", confirmed_fields={"given_names": "Draft"},
        staff_metadata={"verified_whatsapp_numbers": "9876543211"},
    ))
    session.add(PassportRosterResolutionModel(
        agency_id=agency_id, client_group_id=groups["owned"], submission_id=submission_id,
        resolution_type="rejected", status="active",
    ))
    await session.commit()
    response = await client.get(f"/whatsapp/source-groups/{groups['owned']}/preview")
    assert response.status_code == 200
    assert response.json()["total_submissions"] == 0
    assert response.json()["recipients"] == []


@pytest.mark.asyncio
async def test_create_rechecks_actor_deactivation(source_api):
    client, session, groups, _, _ = source_api
    body = await _body(client, groups["owned"])
    user = (await session.execute(select(UserModel))).scalar_one()
    user.is_active = False
    await session.commit()
    response = await client.post("/whatsapp/groups/from-client-group", json=body)
    assert response.status_code == 403
    assert await session.scalar(select(func.count(WhatsAppBroadcastGroupModel.id))) == 0


@pytest.mark.asyncio
async def test_creation_enforces_capacity_before_any_broadcast_mutation(source_api, monkeypatch):
    from app.application.use_cases.whatsapp.recipient_capacity import (
        WhatsAppRecipientCapacityExceeded,
    )

    client, session, groups, _, _ = source_api

    def exhausted_capacity(**_kwargs):
        raise WhatsAppRecipientCapacityExceeded(active_count=0, activating_count=1501)

    monkeypatch.setattr(routes, "require_whatsapp_recipient_capacity", exhausted_capacity)
    response = await client.post("/whatsapp/groups/from-client-group", json=await _body(client, groups["owned"]))
    assert response.status_code == 400
    assert await session.scalar(select(func.count(WhatsAppBroadcastGroupModel.id))) == 0
