from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.realtime_hints import register_mobile_realtime_publisher
from app.application.mobile.sync_journal import append_mobile_sync_change


@pytest.mark.asyncio
async def test_realtime_hint_is_published_only_after_commit_without_journal_payload(
    db_session: AsyncSession,
) -> None:
    captured = []
    unregister = register_mobile_realtime_publisher(captured.append)
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        access_generation=3,
    )
    try:
        await append_mobile_sync_change(
            db_session,
            access=access,  # type: ignore[arg-type]
            entity_type="common_document",
            entity_id=uuid.uuid4(),
            operation="publish",
            version=7,
            changed_by_user_id=None,
            payload={"name": "PRIVATE NAME", "token": "bearer-secret"},
        )

        assert captured == []
        await db_session.commit()

        assert len(captured) == 1
        hints = captured[0]
        assert len(hints) == 1
        hint = hints[0]
        assert hint.agency_id == access.agency_id
        assert hint.trip_id == access.group_id
        assert hint.cursor >= 1
        assert hint.invalidation == "documents"
        serialized = str(hint.redis_payload()) + str(hint.client_payload())
        assert "PRIVATE NAME" not in serialized
        assert "bearer-secret" not in serialized
        assert str(hint.client_payload()).find(str(access.agency_id)) == -1
    finally:
        unregister()


@pytest.mark.asyncio
async def test_rollback_never_publishes_realtime_hint(db_session: AsyncSession) -> None:
    captured = []
    unregister = register_mobile_realtime_publisher(captured.append)
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        access_generation=1,
    )
    try:
        await append_mobile_sync_change(
            db_session,
            access=access,  # type: ignore[arg-type]
            entity_type="announcement",
            entity_id=uuid.uuid4(),
            operation="upsert",
            version=1,
            changed_by_user_id=None,
        )
        await db_session.rollback()
        assert captured == []
    finally:
        unregister()


@pytest.mark.asyncio
async def test_one_transaction_coalesces_trip_to_highest_cursor(
    db_session: AsyncSession,
) -> None:
    captured = []
    unregister = register_mobile_realtime_publisher(captured.append)
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        access_generation=1,
    )
    try:
        first = await append_mobile_sync_change(
            db_session,
            access=access,  # type: ignore[arg-type]
            entity_type="announcement",
            entity_id=uuid.uuid4(),
            operation="upsert",
            version=1,
            changed_by_user_id=None,
        )
        second = await append_mobile_sync_change(
            db_session,
            access=access,  # type: ignore[arg-type]
            entity_type="itinerary",
            entity_id=uuid.uuid4(),
            operation="upsert",
            version=2,
            changed_by_user_id=None,
        )
        await db_session.commit()

        assert len(captured) == 1
        assert len(captured[0]) == 1
        assert captured[0][0].cursor == max(first.sequence, second.sequence)
        assert captured[0][0].invalidation == "all"
    finally:
        unregister()


@pytest.mark.asyncio
async def test_savepoint_commit_does_not_publish_before_outer_commit(
    db_session: AsyncSession,
) -> None:
    captured = []
    unregister = register_mobile_realtime_publisher(captured.append)
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        access_generation=1,
    )
    try:
        outer = await db_session.begin()
        savepoint = await db_session.begin_nested()
        await append_mobile_sync_change(
            db_session,
            access=access,  # type: ignore[arg-type]
            entity_type="announcement",
            entity_id=uuid.uuid4(),
            operation="upsert",
            version=1,
            changed_by_user_id=None,
        )
        await savepoint.commit()
        assert captured == []

        await outer.commit()
        assert len(captured) == 1
        assert captured[0][0].invalidation == "announcements"
    finally:
        unregister()


@pytest.mark.asyncio
async def test_savepoint_rollback_preserves_parent_hint_and_discards_child(
    db_session: AsyncSession,
) -> None:
    captured = []
    unregister = register_mobile_realtime_publisher(captured.append)
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        access_generation=1,
    )
    try:
        outer = await db_session.begin()
        parent = await append_mobile_sync_change(
            db_session,
            access=access,  # type: ignore[arg-type]
            entity_type="itinerary",
            entity_id=uuid.uuid4(),
            operation="upsert",
            version=1,
            changed_by_user_id=None,
        )
        savepoint = await db_session.begin_nested()
        await append_mobile_sync_change(
            db_session,
            access=access,  # type: ignore[arg-type]
            entity_type="common_document",
            entity_id=uuid.uuid4(),
            operation="publish",
            version=2,
            changed_by_user_id=None,
        )
        await savepoint.rollback()
        await outer.commit()

        assert len(captured) == 1
        assert len(captured[0]) == 1
        assert captured[0][0].cursor == parent.sequence
        assert captured[0][0].invalidation == "itinerary"
    finally:
        unregister()
