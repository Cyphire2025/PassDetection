"""Bounded photo preparation preserves visibility and idempotent job ownership."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.dialects import postgresql

from app.application.my_photos.errors import MyPhotosConflict
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import MyPhotoJobModel, MyPhotoMediaAssetModel
from app.infrastructure.my_photos.service import MyPhotosService
from app.presentation.api.v1.schemas.my_photos_schemas import MyPhotosPrepareRequest
from tests.integration.test_my_photos_delivery_freshness import _seed_delivery
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


@pytest.mark.parametrize("state", ["ready", "archived", "missing_archive", "removed", "foreign"])
async def test_media_preparation_visibility_and_replay(photo_database, state):
    env = photo_database
    seeded = await _seed_delivery(env)
    if state != "ready":
        async with env.sessions() as session, session.begin():
            values = {"availability_state": "archived_offline", "storage_reference": None}
            if state == "missing_archive":
                values["archive_reference"] = None
            elif state == "removed":
                values.update(processing_state="removed", availability_state="removed")
            await session.execute(
                update(MyPhotoMediaAssetModel)
                .where(
                    MyPhotoMediaAssetModel.id == seeded.asset_id,
                )
                .values(**values)
            )
    request = MyPhotosPrepareRequest(idempotency_key="synthetic-prepare", quality="original")
    providers = SimpleNamespace(provider_name="aws")
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        args = dict(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            asset_id=uuid.uuid4() if state == "foreign" else seeded.asset_id,
            request=request,
        )
        if state in {"foreign", "removed", "missing_archive"}:
            with pytest.raises(
                MyPhotosConflict if state == "missing_archive" else EntityNotFoundError
            ):
                await service.prepare_media(**args)
            await session.rollback()
        else:
            first = await service.prepare_media(**args)
            await session.commit()
            second = await service.prepare_media(**args)
            await session.commit()
            assert first.preparation_id == second.preparation_id
            if state == "ready":
                assert first.state == second.state == "delivery_available"
                assert first.preparation_id is None
            else:
                assert first.state == "rehydration_requested"
                assert second.state == "preparing_delivery"
                with pytest.raises(MyPhotosConflict):
                    await service.prepare_media(
                        **{
                            **args,
                            "request": request.model_copy(
                                update={"quality": "optimized"},
                            ),
                        }
                    )
                await session.rollback()
    async with env.sessions() as session:
        assert await session.scalar(select(func.count(MyPhotoJobModel.id))) == int(
            state == "archived"
        )


async def test_media_preparation_serializes_before_idempotency_lookup(photo_database):
    env = photo_database
    seeded = await _seed_delivery(env)
    statements = []
    engine = env.sessions.kw["bind"].sync_engine

    def capture(_connection, clause, _multiparams, _params, _options):
        statements.append(str(clause.compile(dialect=postgresql.dialect())))

    event.listen(engine, "before_execute", capture)
    try:
        async with env.sessions() as session:
            service = MyPhotosService(
                session, settings=env.settings, providers=SimpleNamespace(provider_name="aws")
            )
            await service.prepare_media(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                asset_id=seeded.asset_id,
                request=MyPhotosPrepareRequest(
                    idempotency_key="synthetic-lock", quality="original"
                ),
            )
    finally:
        event.remove(engine, "before_execute", capture)
    identity_locks = [
        index
        for index, text in enumerate(statements)
        if "mobile_passenger_identities" in text and "FOR UPDATE" in text
    ]
    job_reads = [index for index, text in enumerate(statements) if "FROM my_photo_jobs" in text]
    assert identity_locks, (
        "Actual ORM execution must lock the identity before first-write replay lookup"
    )
    assert job_reads and identity_locks[0] < job_reads[0]
