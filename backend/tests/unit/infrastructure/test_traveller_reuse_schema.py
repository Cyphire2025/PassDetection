"""Real database constraints; PostgreSQL concurrency is a separate qualification lane."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateColumn, CreateIndex, CreateTable

from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerContactBindingModel,
    TravellerDocumentRevisionModel,
    TravellerHistoryGrantModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)


async def _scope(session: AsyncSession):
    agency = AgencyModel(name="Synthetic agency", email=f"{uuid.uuid4()}@example.invalid")
    session.add(agency)
    await session.flush()
    company = ClientOrganizationModel(agency_id=agency.id, name="Synthetic", normalized_name="synthetic")
    session.add(company)
    await session.flush()
    group = ClientGroupModel(agency_id=agency.id, company_id=company.id, company_revision=1,
                             name="Synthetic trip", token=uuid.uuid4().hex)
    session.add(group)
    await session.flush()
    person = TravellerProfileModel(agency_id=agency.id, company_id=company.id)
    session.add(person)
    await session.flush()
    return agency, company, group, person


def _passport(person: TravellerProfileModel, **overrides):
    values = dict(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
                  issuing_country="IND", document_type="passport", number_fingerprint="a" * 64,
                  number_ciphertext="encrypted-number", fingerprint_key_version="test-v1")
    return TravellerPassportModel(**(values | overrides))


def _revision(passport: TravellerPassportModel, **overrides):
    values = dict(agency_id=passport.agency_id, company_id=passport.company_id,
                  traveller_id=passport.traveller_id, passport_id=passport.id,
                  revision_number=1, fields_ciphertext="encrypted-fields", idempotency_key=uuid.uuid4().hex)
    return TravellerDocumentRevisionModel(**(values | overrides))


@pytest.mark.asyncio
async def test_company_scope_is_enforced_by_database(db_session):
    agency, company, _, person = await _scope(db_session)
    other_agency, _, _, _ = await _scope(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_passport(person, agency_id=other_agency.id))
            await db_session.flush()
@pytest.mark.asyncio
async def test_revision_cannot_reference_another_persons_passport(db_session):
    _, company, _, person = await _scope(db_session)
    other = TravellerProfileModel(agency_id=person.agency_id, company_id=company.id)
    passport = _passport(person)
    db_session.add_all([other, passport])
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_revision(passport, traveller_id=other.id))
            await db_session.flush()


@pytest.mark.asyncio
async def test_shared_phone_is_allowed_but_two_current_contacts_are_not(db_session):
    _, company, _, person = await _scope(db_session)
    other = TravellerProfileModel(agency_id=person.agency_id, company_id=company.id)
    db_session.add(other)
    await db_session.flush()
    def contact(owner):
        return TravellerContactBindingModel(agency_id=owner.agency_id, company_id=owner.company_id,
            traveller_id=owner.id, kind="phone", value_ciphertext="encrypted-phone",
            value_fingerprint="b" * 64, fingerprint_key_version="test-v1", status="current")
    db_session.add_all([contact(person), contact(other)])
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(contact(person))
            await db_session.flush()


@pytest.mark.asyncio
async def test_reuse_cannot_activate_without_purpose_notice_and_basis(db_session):
    agency, company, _, _ = await _scope(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(TravellerReusePolicyModel(agency_id=agency.id, company_id=company.id, enabled=True))
            await db_session.flush()


@pytest.mark.asyncio
async def test_explicit_until_withdrawn_authority_does_not_invent_a_purge_date(db_session):
    agency, company, _, person = await _scope(db_session)
    policy = TravellerReusePolicyModel(agency_id=agency.id, company_id=company.id, enabled=True,
        retention_mode="until_withdrawn", purpose_version="future-trip-v1", notice_version="notice-v1",
        processing_basis="documented-purpose", configured_at=datetime.now(UTC))
    db_session.add(policy)
    person.reuse_permission_status = "granted"
    person.reuse_permission_evidence = {"notice_version": "notice-v1"}
    await db_session.flush()
    assert policy.retention_days is None and person.retention_until is None


@pytest.mark.asyncio
async def test_document_candidate_and_multiple_passports_survive_without_automatic_promotion(db_session):
    _, _, _, person = await _scope(db_session)
    first, second = _passport(person), _passport(person, number_fingerprint="c" * 64)
    db_session.add_all([first, second])
    await db_session.flush()
    db_session.add_all([_revision(first), _revision(second)])
    await db_session.flush()
    assert first.status == second.status == "candidate"
    assert first.is_default is second.is_default is False


@pytest.mark.asyncio
async def test_one_participation_per_person_group_even_with_new_request_key(db_session):
    _, _, group, person = await _scope(db_session)
    def membership():
        return TravellerParticipationModel(agency_id=person.agency_id, company_id=person.company_id,
            traveller_id=person.id, group_id=group.id, source_kind="returning", profile_revision=1,
            contact_revision=1, question_version="v1", idempotency_key=uuid.uuid4().hex)
    db_session.add(membership())
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(membership())
            await db_session.flush()


@pytest.mark.asyncio
async def test_company_cannot_cascade_delete_traveller_history(db_session):
    _, company, _, _ = await _scope(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(delete(ClientOrganizationModel).where(ClientOrganizationModel.id == company.id))


@pytest.mark.asyncio
async def test_grant_is_bound_to_the_exact_claim_person_and_document(db_session):
    _, _, group, person = await _scope(db_session)
    other = TravellerProfileModel(agency_id=person.agency_id, company_id=person.company_id)
    db_session.add(other)
    await db_session.flush()
    first, second = _passport(person), _passport(other)
    db_session.add_all([first, second])
    await db_session.flush()
    first_revision, second_revision = _revision(first), _revision(second)
    db_session.add_all([first_revision, second_revision])
    await db_session.flush()
    now = datetime.now(UTC)
    claim = TravellerClaimModel(agency_id=person.agency_id, company_id=person.company_id,
        group_id=group.id, traveller_id=person.id, passport_id=first.id, document_revision_id=first_revision.id,
        secret_hash="d" * 64, method="passport", max_attempts=5, created_at=now,
        expires_at=now + timedelta(minutes=10), idempotency_key=uuid.uuid4().hex)
    db_session.add(claim)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(TravellerHistoryGrantModel(agency_id=person.agency_id, company_id=person.company_id,
                group_id=group.id, traveller_id=other.id, passport_id=second.id, document_revision_id=second_revision.id,
                claim_id=claim.id, secret_hash="e" * 64, profile_revision=1, contact_revision=1,
                authorization_version=1, company_revision=1, group_revision=1, policy_revision=1,
                actor_kind="self", allowed_actions=["history:read"], created_at=now, last_used_at=now,
                inactivity_expires_at=now + timedelta(minutes=15), absolute_expires_at=now + timedelta(hours=1)))
            await db_session.flush()


def _migration(filename="0131_traveller_reuse.py"):
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("traveller_reuse_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_migration_matches_every_model_constraint_and_index(monkeypatch):
    migration = _migration()
    impact = _migration("0133_traveller_document_impact.py")
    assert migration.down_revision == "0130_company_directory"
    assert impact.down_revision == "0132_traveller_source_seek"
    dialect = postgresql.dialect()
    expected = []
    for table in TravellerProfileModel.metadata.sorted_tables:
        if table.name in (*migration.TABLE_NAMES, "traveller_change_feeds", "traveller_document_review_tasks"):
            expected.append(str(CreateTable(table).compile(dialect=dialect)).strip())
            expected.extend(str(CreateIndex(index).compile(dialect=dialect)).strip()
                            for index in sorted(table.indexes, key=lambda value: value.name))
    # SQLAlchemy stores constraints in sets; process hash randomization may
    # reorder equivalent inline FK/UNIQUE declarations. Compare their exact
    # definitions without treating declaration order as schema drift.
    def canonical(statement):
        return tuple(sorted(line.strip().rstrip(",") for line in statement.splitlines()))
    # Compose the frozen initial schema with real additive migration operations.
    # This verifies both revisions without rewriting the historical 0131 DDL.
    operations = MagicMock()
    monkeypatch.setattr(impact, "op", operations)
    impact.upgrade()
    additions = {}
    for call in operations.add_column.call_args_list:
        table, column = call.args
        additions.setdefault(table, []).append(str(CreateColumn(column).compile(dialect=dialect)))
    for call in operations.create_unique_constraint.call_args_list:
        name, table, columns = call.args
        additions.setdefault(table, []).append(f"CONSTRAINT {name} UNIQUE ({', '.join(columns)})")
    for call in operations.create_check_constraint.call_args_list:
        name, table, expression = call.args
        additions.setdefault(table, []).append(f"CONSTRAINT {name} CHECK ({expression})")
    composed = []
    for statement in (*migration.DDL, *impact.DDL):
        lines = list(canonical(statement))
        for table, extra in additions.items():
            if statement.startswith(f"CREATE TABLE {table} ("):
                lines.extend(line.strip().rstrip(",") for line in extra)
        composed.append(tuple(sorted(lines)))
    assert set(composed) == {canonical(item) for item in expected}


def test_downgrade_refuses_data_loss(monkeypatch):
    migration = _migration()
    operations = MagicMock()
    operations.get_bind.return_value.execute.return_value.scalar_one.return_value = True
    monkeypatch.setattr(migration, "op", operations)
    with pytest.raises(RuntimeError, match="accepted history"):
        migration.downgrade()
    operations.drop_table.assert_not_called()
