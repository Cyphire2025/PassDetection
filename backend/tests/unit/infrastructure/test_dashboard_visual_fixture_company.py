"""Synthetic dashboard fixtures must honor the live canonical-company constraints."""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel, GCGroupAccessModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, UserModel

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "passdetection-real-stack-qa")
AGENCY_ID = uuid.uuid5(NAMESPACE, "agency")
GROUP_ID = uuid.uuid5(NAMESPACE, "group")
OWNER_ID = uuid.uuid5(NAMESPACE, "admin")
COMPANY_ID = uuid.uuid5(NAMESPACE, "gc-client-organization")


@pytest.fixture
def visual_fixture(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts/qa"))
    module = importlib.import_module("dashboard_visual_fixtures")
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(
        app_env="development", database=SimpleNamespace(db="passdetection_ci_fixture_test"),
    ))
    storage = SimpleNamespace(ensure_bucket_exists=AsyncMock(), upload_file=AsyncMock())
    monkeypatch.setattr(module, "MinioStorageRepository", lambda: storage)
    monkeypatch.setitem(sys.modules, "dashboard_whatsapp_fixtures", SimpleNamespace(
        seed_whatsapp_visual_records=AsyncMock(),
    ))
    return module


async def seeded_group(session: AsyncSession) -> ClientGroupModel:
    session.add(AgencyModel(id=AGENCY_ID, name="Synthetic QA agency", email="qa@example.test"))
    await session.flush()
    session.add(UserModel(id=OWNER_ID, agency_id=AGENCY_ID, email="qa-owner@example.test",
                          hashed_password="synthetic", full_name="QA owner", role="super_admin"))
    await session.flush()
    group = ClientGroupModel(id=GROUP_ID, agency_id=AGENCY_ID, name="QA group",
                             token="synthetic-fixture-group", created_by_user_id=OWNER_ID)
    session.add(group)
    await session.commit()
    return group


async def run_seed(module, session: AsyncSession, **overrides) -> None:
    arguments = dict(namespace=NAMESPACE, agency_id=AGENCY_ID, group_id=GROUP_ID,
                     owner_id=OWNER_ID, passenger_ids=())
    await module.seed_visual_records(session, **(arguments | overrides))


async def test_seed_commits_canonical_company_idempotently_and_keeps_access_disabled(
    db_session, visual_fixture,
):
    group = await seeded_group(db_session)
    await run_seed(visual_fixture, db_session)
    await db_session.commit()
    control = await db_session.scalar(select(GCGroupAccessModel))
    assert group.company_id == control.client_organization_id == COMPANY_ID
    assert group.company_revision == 1
    assert not any((control.is_enabled, control.passenger_access_enabled,
                    control.client_manager_access_enabled, control.coordinator_access_enabled))
    await run_seed(visual_fixture, db_session)
    await db_session.commit()
    assert group.company_revision == 1
    assert await db_session.scalar(select(func.count()).select_from(GCGroupAccessModel)) == 1
    assert (await db_session.execute(text("PRAGMA foreign_key_check"))).all() == []
    # Prove the real composite FK remains enforced; a divergent assignment
    # still fails at commit rather than being silently accepted by the fixture.
    group.company_id = None
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("overrides", [{"group_id": uuid.uuid4()}, {"agency_id": uuid.uuid4()}])
async def test_seed_refuses_missing_or_cross_agency_group_before_mutation(
    db_session, visual_fixture, overrides,
):
    group = await seeded_group(db_session)
    with pytest.raises(RuntimeError, match="group.*ownership"):
        await run_seed(visual_fixture, db_session, **overrides)
    assert group.company_id is None
    assert await db_session.scalar(select(func.count()).select_from(ClientOrganizationModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(GCGroupAccessModel)) == 0


async def test_seed_refuses_company_from_another_agency(db_session, visual_fixture):
    group = await seeded_group(db_session)
    other = uuid.uuid4()
    db_session.add(AgencyModel(id=other, name="Other QA agency", email="other@example.test"))
    await db_session.flush()
    db_session.add(ClientOrganizationModel(id=COMPANY_ID, agency_id=other,
                                           name="Other company", normalized_name="other company"))
    await db_session.commit()
    with pytest.raises(RuntimeError, match="company.*ownership"):
        await run_seed(visual_fixture, db_session)
    assert group.company_id is None
    assert await db_session.scalar(select(func.count()).select_from(GCGroupAccessModel)) == 0
