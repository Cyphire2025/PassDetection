"""Real PostgreSQL races; explicitly isolated opt-in database only."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.application.companies.assignment import assign_group_company
from app.application.companies.directory import create_company, update_company
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel, GCGroupAccessModel
from app.infrastructure.database.models import ClientGroupModel
from tests.integration.test_company_directory import company, legacy_group, seed_user
from tests.service_integration.test_fcm_dispatch_postgresql import pg_factory as pg_factory

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


async def test_concurrent_company_names_have_one_winner(pg_factory):
    async with pg_factory() as session:
        user = await seed_user(session)
        await session.commit()

    async def attempt(name):
        async with pg_factory() as session:
            try:
                item = await create_company(session, user=user, agency_id=None, name=name)
                await session.commit()
                return item.id
            except ConflictError:
                await session.rollback()
                return None

    outcomes = await asyncio.wait_for(asyncio.gather(attempt("Concurrent Client"), attempt(" concurrent  CLIENT ")), 15)
    assert sum(item is not None for item in outcomes) == 1
    async with pg_factory() as session:
        assert len((await session.scalars(select(ClientOrganizationModel).where(
            ClientOrganizationModel.agency_id == user.agency_id,
        ))).all()) == 1


async def test_concurrent_group_assignments_and_rename_fence_stale_revisions(pg_factory):
    async with pg_factory() as session:
        user = await seed_user(session)
        first, second = await company(session, user), await company(session, user, "Target")
        group = await legacy_group(session, user)
        await session.commit()

    async def assign(identifier):
        async with pg_factory() as session:
            try:
                await assign_group_company(session, user=user, agency_id=user.agency_id, group_id=group.id,
                                           company_id=identifier, expected_revision=0)
                await session.commit()
                return True
            except ConflictError:
                await session.rollback()
                return False

    assert sum(await asyncio.wait_for(asyncio.gather(assign(first.id), assign(second.id)), 15)) == 1

    async def rename(name):
        async with pg_factory() as session:
            try:
                await update_company(session, user=user, company_id=first.id, agency_id=None,
                                     expected_revision=1, changes={"name": name})
                await session.commit()
                return True
            except ConflictError:
                await session.rollback()
                return False

    assert sum(await asyncio.wait_for(asyncio.gather(rename("Rename A"), rename("Rename B")), 15)) == 1


async def test_database_forbids_gc_company_divergence(pg_factory):
    async with pg_factory() as session:
        user = await seed_user(session)
        first, second = await company(session, user), await company(session, user, "Target")
        group = await legacy_group(session, user)
        await assign_group_company(session, user=user, agency_id=user.agency_id, group_id=group.id,
                                   company_id=first.id, expected_revision=0)
        await session.commit()
    async with pg_factory() as session:
        with pytest.raises(IntegrityError):
            session.add(GCGroupAccessModel(id=uuid.uuid4(), agency_id=user.agency_id, group_id=group.id,
                                          client_organization_id=second.id, is_enabled=False))
            await session.flush()
            await session.execute(text("SET CONSTRAINTS fk_gc_group_canonical_company IMMEDIATE"))
        await session.rollback()
    async with pg_factory() as session:
        assert (await session.get(ClientGroupModel, group.id)).company_id == first.id
