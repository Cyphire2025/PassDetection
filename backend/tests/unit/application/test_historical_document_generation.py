"""Reverification creates a fresh document without rewriting prior trip evidence."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.companies.people import current_document
from app.application.travellers.accepted_source import retained_source_is_current
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.storage.minio_repository import ObjectIntegrityMetadata
from app.infrastructure.travellers import asset_copy
from tests.unit.application.test_company_history_registration import register
from tests.unit.application.test_traveller_enrollment import _fixture
from tests.unit.application.test_traveller_legacy_approval import approve_legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["verification_revision", "verification_time", "source_image"])
async def test_new_ai_generation_at_same_extraction_revision_reenrolls_and_copies(db_session, monkeypatch, change):
    ctx = await _fixture(db_session)
    approve_legacy(ctx.source)
    await db_session.flush()
    person_id = await register(db_session, ctx)
    old = await db_session.scalar(select(Document))
    previous = deepcopy(old.source_provenance)
    original_fields = dict(ctx.source.confirmed_fields)
    old_membership = await db_session.scalar(select(Participation))
    assert old_membership.document_revision_id == old.id
    assert await db_session.scalar(select(func.count()).select_from(Asset).where(Asset.availability == "pending")) == 2
    if change == "verification_revision":
        ctx.source.post_submission_verification_revision = 2
    elif change == "verification_time":
        ctx.source.post_submission_verified_at += timedelta(seconds=1)
    else:
        ctx.source.image_s3_key = "new/front.jpg"
    await db_session.flush()
    assert ctx.source.extraction_revision == 1
    assert not retained_source_is_current(old, ctx.source, ctx.crypto)
    assert await register(db_session, ctx) == person_id
    documents = list((await db_session.scalars(select(Document).order_by(Document.revision_number))).all())
    assert len(documents) == 2
    latest = documents[-1]
    assert latest.id != old.id and latest.revision_number == old.revision_number + 1
    assert latest.idempotency_key != old.idempotency_key and len(latest.idempotency_key) <= 128
    assert old.source_provenance == previous and old.status == "accepted"
    assert old_membership.document_revision_id == old.id
    assert ctx.source.confirmed_fields == original_fields and ctx.source.extraction_revision == 1
    assert retained_source_is_current(latest, ctx.source, ctx.crypto)
    person = await db_session.get(Person, person_id)
    assert (await current_document(db_session, person))[1].id == latest.id
    assert await register(db_session, ctx) == person_id
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 2
    assert await db_session.scalar(select(func.count()).select_from(Person)) == 1

    # Inject this fixture's encryption context; exercise the real copy authority.
    monkeypatch.setattr(asset_copy, "retained_source_is_current",
        lambda revision, source: retained_source_is_current(revision, source, ctx.crypto))
    assets = list((await db_session.scalars(select(Asset))).all())
    for asset in assets:
        assert await asset_copy._has_copy_authority(db_session, asset, datetime.now(UTC)) == (asset.document_revision_id == latest.id)
    old_id, latest_id = old.id, latest.id
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = SimpleNamespace(stat_file=AsyncMock(return_value=ObjectIntegrityMetadata(4096, "a" * 64, "image/jpeg")),
        copy_file=AsyncMock(return_value="copied"))
    # Invalid old claims are consumed without copying; two new copies succeed.
    for _ in range(5):
        await asset_copy.copy_next_asset(session_factory=factory, storage=storage)
    db_session.expire_all()
    assets = list((await db_session.scalars(select(Asset))).all())
    assert all(asset.availability == "unreadable" for asset in assets if asset.document_revision_id == old_id)
    assert all(asset.availability == "available" for asset in assets if asset.document_revision_id == latest_id)
    assert storage.copy_file.await_count == 2
