"""Exercise the client-details HTTP boundary with real persistence and response building."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    Base,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.passport_routes import client_details
from app.presentation.dependencies.auth import get_current_active_user


@pytest.fixture
async def correction_session(db_session: AsyncSession):
    url = os.environ.get("CLIENT_DETAILS_TEST_DATABASE_URL")
    if not url:
        yield db_session
        return
    assert make_url(url).host in {"localhost", "127.0.0.1"}, "Use an isolated local test database"
    schema = f"client_details_test_{uuid.uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as session:
            yield session
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mobile_enabled", [False, True])
@pytest.mark.parametrize("broadcast_policy", ["unlinked", "legacy", "selected"])
async def test_client_detail_correction_real_http_transaction(
    correction_session: AsyncSession, mobile_enabled: bool, broadcast_policy: str
) -> None:
    db_session = correction_session
    now = datetime.now(tz=UTC)
    agency_id, group_id, user_id, submission_id = (uuid.uuid4() for _ in range(4))
    actor = User(
        user_id, "reviewer@example.test", "not-a-password", "Reviewer", UserRole.SUPER_ADMIN, None
    )
    group = ClientGroupModel(
        id=group_id,
        agency_id=agency_id,
        name="Synthetic trip",
        token=str(uuid.uuid4()),
        status="active",
        agent_employee_code_enabled=True,
        departure_cities=[],
    )
    submission = PassportSubmissionModel(
        id=submission_id,
        agency_id=agency_id,
        group_id=group_id,
        client_name="Test traveller",
        client_email="traveller@example.test",
        client_phone="9876543210",
        image_s3_key="synthetic/passport.jpg",
        status="ai_approved",
        confirmed_fields={"passport_number": "P1234567", "agent_employee_code": "AIG12345"},
        extracted_fields={"passport_number": "P1234567"},
        staff_metadata={"agent_employee_code_label": "Producer Code"},
        created_at=now,
        updated_at=now,
    )
    db_session.add_all(
        [
            AgencyModel(id=agency_id, name="Synthetic agency", email="agency@example.test"),
            UserModel(
                id=user_id,
                email=actor.email,
                full_name=actor.full_name,
                hashed_password="not-a-password",
                role=actor.role.value,
            ),
            group,
            submission,
        ]
    )
    await db_session.flush()
    if broadcast_policy != "unlinked":
        broadcast_id = uuid.uuid4()
        db_session.add(
            WhatsAppBroadcastGroupModel(
                id=broadcast_id,
                agency_id=agency_id,
                name="Synthetic broadcast",
                organizing_company_name="Synthetic agency",
                recipient_opt_in_confirmed_at=now,
            )
        )
        await db_session.flush()
        db_session.add_all(
            [
                ClientGroupWhatsAppBroadcastLinkModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    client_group_id=group_id,
                    broadcast_group_id=broadcast_id,
                    matching_field_keys=["producer_code"]
                    if broadcast_policy == "selected"
                    else None,
                ),
                WhatsAppBroadcastRecipientModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    broadcast_group_id=broadcast_id,
                    name="Qualified person",
                    phone_number="+919876543210",
                    normalized_phone_number="+919876543210",
                    imported_fields={"producer_code": "12345"},
                ),
            ]
        )
    # SQLite's timestamp round-trip drops timezone data. Exercise the real QR
    # response against PostgreSQL, where production timestamps retain their zone.
    if db_session.get_bind().dialect.name == "postgresql":
        db_session.add(
            PassengerQRTokenModel(
                id=uuid.uuid4(),
                agency_id=agency_id,
                passenger_id=submission_id,
                token_hash=uuid.uuid4().hex,
                token_version=1,
                is_active=True,
                expires_at=now + timedelta(days=30),
                created_at=now,
            )
        )
    if mobile_enabled:
        db_session.add(
            GCGroupAccessModel(
                id=uuid.uuid4(),
                agency_id=agency_id,
                group_id=group_id,
                is_enabled=True,
                passenger_access_enabled=True,
                coordinator_access_enabled=True,
            )
        )
    await db_session.commit()

    app = FastAPI()
    app.include_router(client_details.router, prefix="/api/v1/passports")

    async def database():
        yield db_session

    async def user():
        return actor

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_current_active_user] = user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        url = f"/api/v1/passports/{submission_id}/client-details"
        editor = await client.get(url)
        assert editor.status_code == 200, editor.text
        version = editor.json()["updated_at"]
        # SQLite stores a naive UTC timestamp; the production PostgreSQL value
        # carries its zone. Preserve its instant when sending the HTTP token.
        if not version.endswith("Z") and "+" not in version:
            version += "Z"
        response = await client.patch(
            url,
            json={
                "expected_updated_at": version,
                "agent_employee_code": "12345",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["confirmed_fields"]["agent_employee_code"] == "12345"
        assert response.json()["status"] == "ai_approved"
        if db_session.get_bind().dialect.name == "postgresql":
            assert response.json()["qr_status"]["status"] == "active"

    await db_session.refresh(submission)
    assert submission.confirmed_fields["agent_employee_code"] == "12345"
    audit = (
        await db_session.execute(
            select(AuditLogModel).where(
                AuditLogModel.entity_id == str(submission_id),
                AuditLogModel.action == "passport_client_details_corrected",
            )
        )
    ).scalar_one()
    assert audit.user_id == user_id
    assert audit.metadata_json["changed_fields"] == ["agent_employee_code"]
