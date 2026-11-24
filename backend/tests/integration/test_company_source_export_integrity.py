"""Historical references cannot stall a bounded private source-image export."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.application.companies.export_source import IMAGE_PAGE_SIZE, source_image_page
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as MatchCase
from tests.integration.test_company_people import people_fixture


async def test_malformed_historical_references_advance_without_exposing_an_object(db_session):
    context, person, user = await people_fixture(db_session)
    for index in range(IMAGE_PAGE_SIZE):
        db_session.add(
            MatchCase(
                id=uuid.UUID(int=index + 1),
                agency_id=person.agency_id,
                company_id=person.company_id,
                group_id=context.group.id,
                traveller_id=person.id,
                source_kind="passport_submission",
                source_row_key=f"legacy-invalid-{index}",
                status="resolved",
                reason_code="operator_historical_registration",
            )
        )
    valid_case = MatchCase(
        id=uuid.UUID(int=IMAGE_PAGE_SIZE + 1),
        agency_id=person.agency_id,
        company_id=person.company_id,
        group_id=context.group.id,
        traveller_id=person.id,
        source_kind="passport_submission",
        source_row_key=str(context.source.id),
        status="resolved",
        reason_code="operator_historical_registration",
    )
    db_session.add(valid_case)
    await db_session.flush()
    job = SimpleNamespace(
        agency_id=person.agency_id,
        company_id=person.company_id,
        phase="source_front",
        cursor=None,
        created_at=datetime.now(UTC),
    )
    first = await source_image_page(db_session, job, user)
    assert len(first) == IMAGE_PAGE_SIZE
    assert all(row.key == "" and row.size == 0 for row in first)
    job.cursor = first[-1].identifier
    second = await source_image_page(db_session, job, user)
    assert len(second) == 1 and second[0].identifier == valid_case.id
    assert second[0].key == context.source.image_s3_key
    assert second[0].revision_id == context.source.id
    job.cursor = second[-1].identifier
    assert await source_image_page(db_session, job, user) == []
