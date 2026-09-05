from __future__ import annotations

import uuid
from unittest.mock import Mock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.documents import passport_import_compensation as compensation


@pytest.mark.parametrize("server_committed", [True, False])
async def test_fresh_reference_check_survives_lost_commit_acknowledgement(
    monkeypatch: pytest.MonkeyPatch, server_committed: bool
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine)
    retained = "passport-bulk/synthetic/committed.jpg"
    orphaned = "passport-bulk/synthetic/orphaned.jpg"
    stage = Mock(return_value=())
    monkeypatch.setattr(compensation, "stage_storage_cleanup_jobs", stage)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE passport_submissions (image_s3_key TEXT, passport_photo_s3_key TEXT, passport_back_s3_key TEXT)"
                )
            )
            await connection.execute(
                text("CREATE TABLE passport_image_library_items (storage_key TEXT)")
            )
        async with factory() as failed_session:
            await failed_session.execute(
                text("INSERT INTO passport_submissions VALUES (:key,NULL,NULL)"), {"key": retained}
            )
            if server_committed:
                await failed_session.commit()
                # Exactly the unknown outcome boundary: the server persisted,
                # but the connection reports failure to its caller.
                with pytest.raises(ConnectionError):
                    raise ConnectionError("Commit acknowledgement was lost")
            await failed_session.rollback()
        assert await compensation.reconcile_failed_passport_import(
            agency_id=uuid.uuid4(),
            import_id=uuid.uuid4(),
            uploaded_keys=[retained, orphaned],
            commit_attempted=True,
            session_factory=factory,
        )
        expected = [orphaned] if server_committed else [retained, orphaned]
        assert stage.call_args.kwargs["storage_keys"] == expected
        assert stage.call_args.kwargs["source"] == "passport_submission_delete"
    finally:
        await engine.dispose()


async def test_unavailable_reference_check_retains_every_uncertain_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = Mock()
    monkeypatch.setattr(compensation, "stage_storage_cleanup_jobs", stage)
    assert not await compensation.reconcile_failed_passport_import(
        agency_id=uuid.uuid4(),
        import_id=uuid.uuid4(),
        uploaded_keys=["passport-bulk/synthetic/uncertain.jpg"],
        commit_attempted=True,
        session_factory=Mock(side_effect=ConnectionError("database unavailable")),
    )
    stage.assert_not_called()
