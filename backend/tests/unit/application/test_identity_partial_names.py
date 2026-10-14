"""Synthetic names model repeated surnames, shortened names and middle names."""

import uuid

import pytest
from sqlalchemy import event

from app.application.travellers.identity_index import find_exact_identity, replace_identity_evidence
from app.domain.services.traveller_identity import identity_evidence
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel
from tests.unit.application.test_traveller_enrollment import _fixture


async def indexed_person(session, ctx, name, *, number="P1234", email="person@example.test"):
    person = TravellerProfileModel(agency_id=ctx.group.agency_id, company_id=ctx.group.company_id,
        status="active", display_name_ciphertext=ctx.crypto.encrypt(name))
    session.add(person)
    await session.flush()
    await replace_identity_evidence(session, person=person, crypto=ctx.crypto, source={"synthetic": True},
        evidence=identity_evidence({"name": name, "passport_number": number,
            "phone": "+919999999999", "email": email, "date_of_birth": "1990-01-01"}))
    return person


async def lookup(session, ctx, name="Synthetic", **overrides):
    evidence = identity_evidence({"name": name, "passport_number": "P1234",
        "phone": "+919999999999", "email": "person@example.test", "date_of_birth": "1990-01-01", **overrides})
    return await find_exact_identity(session, agency_id=ctx.group.agency_id,
        company_id=ctx.group.company_id, evidence=evidence, crypto=ctx.crypto)


@pytest.mark.asyncio
async def test_partial_name_uses_exact_passport_index_and_keeps_tenant_scope(db_session):
    ctx, other = await _fixture(db_session), await _fixture(db_session)
    person = await indexed_person(db_session, ctx, "Synthetic Middle Family")
    result = await lookup(db_session, ctx)
    assert result.traveller_id == person.id and result.reason == "corroborated_partial_name_match"
    assert (await lookup(db_session, other)).traveller_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("other_name", ["Synthetic Other Family", "Completely Different Holder"])
async def test_partial_name_never_selects_between_multiple_exact_passport_owners(db_session, other_name):
    ctx = await _fixture(db_session)
    await indexed_person(db_session, ctx, "Synthetic Middle Family")
    await indexed_person(db_session, ctx, other_name, email="different@example.test")
    result = await lookup(db_session, ctx)
    assert result.status == "ambiguous" and result.traveller_id is None


@pytest.mark.asyncio
async def test_partial_name_rejects_wrong_name_and_supplied_dob_conflict(db_session):
    ctx = await _fixture(db_session)
    await indexed_person(db_session, ctx, "Synthetic Middle Family")
    assert (await lookup(db_session, ctx, "Other Person")).traveller_id is None
    result = await lookup(db_session, ctx, date_of_birth="1991-01-01")
    assert result.status == "conflicting" and result.traveller_id is None


@pytest.mark.asyncio
async def test_candidate_overflow_is_bounded_before_signal_loading(db_session):
    ctx = await _fixture(db_session)
    for index in range(101):
        await indexed_person(db_session, ctx, f"Synthetic Candidate {index}")
    queries = []
    connection = await db_session.connection()
    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)
    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        result = await lookup(db_session, ctx)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert result.status == "ambiguous" and result.reason == "candidate_limit_exceeded"
    assert len(queries) == 1  # Unioned indexed seeks; no history/signal hydration.


@pytest.mark.asyncio
async def test_exact_name_keeps_existing_rule_with_unrelated_passport_owner(db_session):
    ctx = await _fixture(db_session)
    person = await indexed_person(db_session, ctx, "Synthetic")
    await indexed_person(db_session, ctx, str(uuid.uuid4()), email="different@example.test")
    assert (await lookup(db_session, ctx)).traveller_id == person.id
