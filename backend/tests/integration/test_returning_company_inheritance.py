"""The company switch covers attached rosters without broadening unlinked access."""
from datetime import UTC, datetime

import pytest

from app.application.travellers.authority import active_scope, eligible_person
from app.application.travellers.errors import ReuseError
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerReusePolicyModel,
)
from tests.integration.test_operational_autoassignment import assign
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person


@pytest.mark.asyncio
async def test_attached_broadcast_inherits_closed_reuse_but_never_grants_unmatched_person(db_session, test_settings):
    service, company, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    await db_session.delete(await db_session.get(TravellerGroupReuseConfigModel, group.id))
    await db_session.flush()
    with pytest.raises(ReuseError):
        await active_scope(db_session, group_id=group.id)
    broadcast = WhatsAppBroadcastGroupModel(agency_id=group.agency_id, name="Synthetic linked roster")
    db_session.add(broadcast)
    await db_session.flush()
    link = ClientGroupWhatsAppBroadcastLinkModel(agency_id=group.agency_id, client_group_id=group.id,
        broadcast_group_id=broadcast.id, matching_field_keys=["name"])
    db_session.add(link)
    await db_session.flush()
    scope = await active_scope(db_session, group_id=group.id)
    assert scope.config.roster_mode == "closed" and scope.config.individual_identifier_type == "company_individual_code"
    with pytest.raises(ReuseError):
        await eligible_person(db_session, scope, person.profile.id, datetime.now(UTC))
    assert await assign(service, group, person) == "assigned"
    assert (await eligible_person(db_session, scope, person.profile.id, datetime.now(UTC))).id == person.profile.id
    policy = await db_session.get(TravellerReusePolicyModel, company.id)
    policy.enabled = False
    await db_session.flush()
    with pytest.raises(ReuseError):
        await active_scope(db_session, group_id=group.id)
    policy.enabled = True
    await db_session.delete(link)
    await db_session.flush()
    with pytest.raises(ReuseError):
        await active_scope(db_session, group_id=group.id)


@pytest.mark.asyncio
async def test_existing_explicit_no_broadcast_config_remains_unchanged(db_session, test_settings):
    _, _, group = await reuse_context(db_session, test_settings)
    scope = await active_scope(db_session, group_id=group.id)
    assert scope.config.roster_mode == "open" and scope.config.individual_identifier_type == "employee"
