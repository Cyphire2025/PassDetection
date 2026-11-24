"""Accepted trip dates must not crash the dashboard approval QR workflow."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from app.domain.entities.entities import ClientGroup
from app.infrastructure.database.models import PassengerQRTokenModel, PassportSubmissionModel
from app.infrastructure.qr.approved_passenger_qr_issuer import (
    ensure_approved_passenger_qr,
    qr_expires_at_for_group,
)
from app.presentation.api.v1.schemas.client_group_request_schemas import CreateClientGroupRequest
from tests.unit.application.test_traveller_reconciliation import _seed_scope


@pytest.mark.parametrize(
    ("returned", "expiry"),
    [
        (date(9999, 12, 29), date.max),
        (date(9999, 12, 30), date.max),
        (date.max, date.max),
        (date(2028, 2, 28), date(2028, 3, 1)),
        (date(2030, 12, 31), date(2031, 1, 2)),
    ],
)
@pytest.mark.asyncio
async def test_persisted_approved_passenger_receives_one_bounded_qr(db_session, returned, expiry):
    agency, company, group = await _seed_scope(db_session)
    request = CreateClientGroupRequest(
        company_id=company.id,
        name="Synthetic QR trip",
        destination="Synthetic",
        travel_date=date(returned.year, 1, 1),
        return_date=returned,
    )
    accepted = ClientGroup.create(
        name=request.name,
        token="synthetic-qr-calendar",
        agency_id=agency.id,
        created_by_user_id=uuid.uuid4(),
        travel_date=request.travel_date,
        return_date=request.return_date,
    )
    group.travel_date, group.return_date = accepted.travel_date, accepted.return_date
    passenger = PassportSubmissionModel(
        agency_id=agency.id,
        group_id=group.id,
        client_name="Synthetic calendar passenger",
        image_s3_key="synthetic/qr-calendar.jpg",
        status="staff_approved",
    )
    db_session.add(passenger)
    await db_session.commit()

    token = await ensure_approved_passenger_qr(db_session, passenger.id)

    assert token is not None
    assert token.expires_at == datetime.combine(expiry, time.max, tzinfo=UTC)
    assert token.expires_at <= datetime.max.replace(tzinfo=UTC)
    assert token.token_version == 1 and token.qr_payload.startswith("pdatt:")
    assert await ensure_approved_passenger_qr(db_session, passenger.id) is token
    assert await db_session.scalar(select(func.count()).select_from(PassengerQRTokenModel)) == 1


@pytest.mark.asyncio
async def test_maximum_trip_date_does_not_issue_for_unapproved_passenger(db_session):
    agency, _, group = await _seed_scope(db_session)
    group.return_date = date.max
    passenger = PassportSubmissionModel(
        agency_id=agency.id,
        group_id=group.id,
        client_name="Synthetic unapproved passenger",
        image_s3_key="synthetic/unapproved-calendar.jpg",
        status="submitted",
    )
    db_session.add(passenger)
    await db_session.commit()

    assert await ensure_approved_passenger_qr(db_session, passenger.id) is None
    assert await db_session.scalar(select(func.count()).select_from(PassengerQRTokenModel)) == 0


def test_no_return_date_keeps_existing_year_ttl():
    group = ClientGroup.create(
        name="Synthetic undated QR trip",
        token="synthetic-undated-calendar",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
    )
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)

    assert qr_expires_at_for_group(group, now) == now + timedelta(days=365)
