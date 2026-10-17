"""Assignment persists across requests without mutating historical source data."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.entities.entities import GroupStatus
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.client_groups import router
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.middleware.error_handler import register_exception_handlers
from tests.integration.test_company_directory import company, legacy_group, seed_user


def application(session_factory, user):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/upload-links")
    register_exception_handlers(app)

    async def transaction():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = transaction
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[require_cookie_csrf] = lambda: None
    return app


async def source_snapshot(session, group_id, broadcast_id):
    tables = (
        (PassportSubmissionModel.__table__, PassportSubmissionModel.group_id == group_id),
        (ClientGroupWhatsAppBroadcastLinkModel.__table__, ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id),
        (WhatsAppBroadcastGroupModel.__table__, WhatsAppBroadcastGroupModel.id == broadcast_id),
        (WhatsAppBroadcastRecipientModel.__table__, WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast_id),
    )
    return [(await session.execute(select(table).where(predicate))).mappings().all() for table, predicate in tables]


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle", [GroupStatus.ACTIVE, GroupStatus.CLOSED, GroupStatus.ARCHIVED])
async def test_import_group_assignment_commits_and_lists_current_company_without_source_changes(db_session, lifecycle):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    group = await legacy_group(db_session, user, lifecycle)
    row = await db_session.get(ClientGroupModel, group.id)
    row.import_only = True
    row.passport_purge_at = datetime.now(UTC) + timedelta(days=90)
    row.passport_legal_hold = True
    row.passport_legal_hold_reason = "Synthetic preservation regression"
    row.passport_legal_hold_set_at = datetime.now(UTC)
    row.passport_legal_hold_set_by_user_id = user.id
    broadcast = WhatsAppBroadcastGroupModel(agency_id=user.agency_id, name="Retained independent broadcast")
    db_session.add(broadcast)
    await db_session.flush()
    db_session.add_all([
        PassportSubmissionModel(agency_id=user.agency_id, group_id=group.id, client_name="Retained person",
            client_phone="+919999999999", status="staff_approved", image_s3_key="retained/passport.png",
            confirmed_fields={"surname": "Retained", "given_names": "Person"}, staff_metadata={"import_row": "001"}),
        ClientGroupWhatsAppBroadcastLinkModel(agency_id=user.agency_id, client_group_id=group.id,
            broadcast_group_id=broadcast.id, matching_field_keys=["name"]),
        WhatsAppBroadcastRecipientModel(agency_id=user.agency_id, broadcast_group_id=broadcast.id,
            name="Independent broadcast person", phone_number="+919999999998", normalized_phone_number="+919999999998",
            imported_fields={"staff_code": "0007"}),
    ])
    await db_session.flush()
    before = await source_snapshot(db_session, group.id, broadcast.id)
    preserved = {key: getattr(row, key) for key in ("status", "import_only", "token", "closed_at", "passport_purge_at",
        "passport_legal_hold", "passport_legal_hold_reason", "passport_legal_hold_set_at",
        "passport_legal_hold_set_by_user_id", "travel_date", "return_date", "upload_configuration")}
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user)
    url = f"/api/v1/upload-links/{group.id}/company"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.patch(url, params={"agency_id": str(user.agency_id)}, json={
            "company_id": str(client.id), "expected_revision": 0,
        })
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["company_id"] == str(client.id) and saved["company_revision"] == 1
        assert saved["company"] == {"id": str(client.id), "name": client.name, "status": "active", "logo_url": None}
        assert saved["status"] == lifecycle.value and saved["import_only"] is True
        listed = await http.get("/api/v1/upload-links", params={"status_filter": lifecycle.value})
        assert listed.status_code == 200
        assert [(entry["company_id"], entry["company_revision"], entry["company"]) for entry in listed.json()] == [
            (saved["company_id"], saved["company_revision"], saved["company"]),
        ]
        # A stale browser cannot repeat or overwrite the committed assignment.
        stale = await http.patch(url, params={"agency_id": str(user.agency_id)}, json={
            "company_id": str(client.id), "expected_revision": 0,
        })
        assert stale.status_code == 409
        same = await http.patch(url, params={"agency_id": str(user.agency_id)}, json={
            "company_id": str(client.id), "expected_revision": 1,
        })
        assert same.status_code == 200 and same.json()["company_revision"] == 1
    async with factory() as verification:
        assert await source_snapshot(verification, group.id, broadcast.id) == before
        stored = await verification.get(ClientGroupModel, group.id)
        for key, value in preserved.items():
            actual = getattr(stored, key)
            if isinstance(value, datetime):
                assert actual.replace(tzinfo=None) == value.replace(tzinfo=None)
            else:
                assert actual == value


@pytest.mark.asyncio
async def test_assignment_rejects_foreign_company_and_wrong_tenant_without_mutation(db_session):
    user, other = await seed_user(db_session), await seed_user(db_session)
    client, foreign = await company(db_session, user), await company(db_session, other)
    group = await legacy_group(db_session, user, GroupStatus.ARCHIVED)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        url = f"/api/v1/upload-links/{group.id}/company"
        foreign_company = await http.patch(url, json={"company_id": str(foreign.id), "expected_revision": 0})
        assert foreign_company.status_code == 422
        foreign_scope = await http.patch(url, params={"agency_id": str(other.agency_id)},
            json={"company_id": str(client.id), "expected_revision": 0})
        assert foreign_scope.status_code == 403
    async with factory() as verification:
        stored = await verification.get(ClientGroupModel, group.id)
        assert stored.company_id is None and stored.company_revision == 0 and stored.status == "archived"
