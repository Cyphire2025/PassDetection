"""An accepted persisted trip date must produce a decision instead of a crash."""

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from app.domain.entities.entities import ClientGroup
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel
from app.presentation.api.v1.schemas.client_group_request_schemas import CreateClientGroupRequest
from tests.integration.test_operational_autoassignment import assign
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person


@pytest.mark.asyncio
async def test_accepted_extreme_trip_date_retains_replacement_workflow(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    request = CreateClientGroupRequest(company_id=group.company_id, name="Synthetic future trip",
                                       destination="Synthetic", travel_date="9999-07-01",
                                       return_date="9999-07-02")
    accepted = ClientGroup.create(name=request.name, token="synthetic-future-trip",
                                  agency_id=group.agency_id, created_by_user_id=uuid.uuid4(),
                                  travel_date=request.travel_date, return_date=request.return_date)
    group.travel_date, group.return_date = accepted.travel_date, accepted.return_date
    person.document.expiry_date = date.max
    await db_session.commit()

    assert await assign(service, group, person) == "replacement_required"
    pending = await db_session.scalar(select(TravellerParticipationModel))
    assert pending is not None and pending.status == "pending"
    assert pending.source_submission_id is None and pending.document_revision_id is None
    assert pending.confirmations["information_confirmed"] is False
    assert await assign(service, group, person) == "replacement_required"
    assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
