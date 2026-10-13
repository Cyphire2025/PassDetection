"""Company-only removal keeps source rows, history and unrelated app access."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.application.companies import removal
from app.application.companies.directory import delete_company
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.gc_mobile_models import ClientManagerGroupAssignmentModel, ClientManagerProfileModel, GCGroupAccessModel
from app.infrastructure.database.models import PassportSubmissionModel
from tests.integration.test_company_directory import company, seed_user
from tests.integration.test_company_summary import assigned_group


@pytest.mark.asyncio
@pytest.mark.parametrize("previously_revoked", [False, True])
async def test_removal_detaches_groups_and_keeps_documents_profiles_and_revoked_grants(db_session, previously_revoked):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    group = await assigned_group(db_session, user, client)
    profile = ClientManagerProfileModel(agency_id=user.agency_id, user_id=user.id, organization_id=client.id,
        normalized_phone_number="+919999999999", status="active", activated_at=datetime.now(UTC))
    access = GCGroupAccessModel(agency_id=user.agency_id, group_id=group.id, client_organization_id=client.id,
        is_enabled=True, passenger_access_enabled=True, coordinator_access_enabled=True, client_manager_access_enabled=True)
    source = PassportSubmissionModel(agency_id=user.agency_id, group_id=group.id, client_name="Retained",
        client_phone="+918888888888", image_s3_key="unchanged.jpg", confirmed_fields={"passport_number": "TEST1234"})
    db_session.add_all([profile, access, source])
    await db_session.flush()
    grant = ClientManagerGroupAssignmentModel(agency_id=user.agency_id, organization_id=client.id,
        profile_id=profile.id, gc_group_access_id=access.id, group_id=group.id, is_active=True)
    old_revocation = datetime(2025, 1, 1, tzinfo=UTC)
    if previously_revoked:
        grant.is_active, grant.revoked_at = False, old_revocation
    db_session.add(grant)
    await db_session.flush()
    before = (await db_session.execute(select(PassportSubmissionModel.__table__).where(PassportSubmissionModel.id == source.id))).mappings().one()
    await delete_company(db_session, user=user, company_id=client.id, agency_id=None, expected_revision=1)
    await db_session.flush()
    assert client.status == "deleted" and client.revision == 2
    await db_session.refresh(grant)
    assert group.company_id is None and group.company_revision == 2
    assert access.client_organization_id is None and not access.client_manager_access_enabled
    assert access.is_enabled and access.passenger_access_enabled and access.coordinator_access_enabled
    assert not grant.is_active and grant.organization_id is None and grant.revoked_at is not None
    if previously_revoked:
        assert grant.revoked_at.replace(tzinfo=UTC) == old_revocation
        assert grant.revoked_by_user_id is None
    assert profile.organization_id == client.id and profile.status == "active"
    after = (await db_session.execute(select(PassportSubmissionModel.__table__).where(PassportSubmissionModel.id == source.id))).mappings().one()
    assert before == after
    # A detached historical grant cannot be reactivated without a valid company.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            grant.is_active, grant.revoked_at, grant.revoked_by_user_id = True, None, None
            await db_session.flush()


@pytest.mark.asyncio
async def test_removal_limit_rejects_before_any_mutation(db_session, monkeypatch):
    user = await seed_user(db_session)
    client = await company(db_session, user)
    rows = [await assigned_group(db_session, user, client) for _ in range(2)]
    monkeypatch.setattr(removal, "MAX_REMOVAL_GROUPS", 1)
    with pytest.raises(ConflictError, match="too many groups"):
        await delete_company(db_session, user=user, company_id=client.id, agency_id=None, expected_revision=1)
    assert client.status == "active" and client.revision == 1
    assert all(group.company_id == client.id and group.company_revision == 1 for group in rows)
