from __future__ import annotations

import uuid

import pytest

from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)


@pytest.mark.asyncio
async def test_direct_feed_is_user_scoped_and_legacy_broadcasts_are_excluded(
    db_session,
) -> None:
    repository = NotificationRepository(db_session)
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    direct = await repository.create(
        agency_id=agency_id,
        user_id=owner_id,
        type="email_ai_attention",
        title="Reply needs review",
        message="A prepared reply is ready.",
        entity_type="email_message",
        entity_id=str(uuid.uuid4()),
        priority="high",
        category="email_operations",
        dedupe_key="analysis:one:ready",
    )
    await repository.create(
        agency_id=agency_id,
        user_id=other_user_id,
        type="email_ai_attention",
        title="Other mailbox",
        message="Must remain private.",
    )
    await repository.create(
        agency_id=agency_id,
        user_id=None,
        type="legacy_broadcast",
        title="Agency notice",
        message="Legacy shared notice.",
    )
    await db_session.flush()

    items, unread_count, next_cursor = await repository.list_direct_feed(
        user_id=owner_id,
        agency_id=agency_id,
        limit=30,
    )

    assert [item.id for item in items] == [direct.id]
    assert unread_count == 1
    assert next_cursor is None


@pytest.mark.asyncio
async def test_direct_feed_uses_stable_cursor_and_server_unread_count(db_session) -> None:
    repository = NotificationRepository(db_session)
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    created = []
    for index in range(3):
        created.append(
            await repository.create(
                agency_id=agency_id,
                user_id=owner_id,
                type="email_deadline",
                title=f"Deadline {index}",
                message="Review deadline.",
                priority="normal",
                category="email_operations",
                dedupe_key=f"deadline:{index}",
            )
        )
    await db_session.flush()

    first_page, unread_count, cursor = await repository.list_direct_feed(
        user_id=owner_id,
        agency_id=agency_id,
        limit=2,
    )
    assert len(first_page) == 2
    assert unread_count == 3
    assert cursor is not None

    second_page, second_count, second_cursor = await repository.list_direct_feed(
        user_id=owner_id,
        agency_id=agency_id,
        cursor=cursor,
        limit=2,
    )
    assert len(second_page) == 1
    assert second_count == 3
    assert second_cursor is None
    assert {item.id for item in first_page + second_page} == {
        item.id for item in created
    }


@pytest.mark.asyncio
async def test_dedupe_and_mark_all_apply_only_to_direct_owner_rows(db_session) -> None:
    repository = NotificationRepository(db_session)
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    first = await repository.create(
        agency_id=agency_id,
        user_id=owner_id,
        type="email_ai_attention",
        title="First",
        message="First",
        dedupe_key="same-analysis",
    )
    duplicate = await repository.create(
        agency_id=agency_id,
        user_id=owner_id,
        type="email_ai_attention",
        title="Changed title is ignored",
        message="Changed message is ignored",
        dedupe_key="same-analysis",
    )
    await repository.create(
        agency_id=agency_id,
        user_id=other_user_id,
        type="email_ai_attention",
        title="Other",
        message="Other",
    )
    await db_session.flush()

    assert duplicate.id == first.id
    assert (
        await repository.mark_all_direct_read(
            user_id=owner_id,
            agency_id=agency_id,
        )
        == 1
    )

    owner_items, owner_unread, _ = await repository.list_direct_feed(
        user_id=owner_id,
        agency_id=agency_id,
        limit=10,
    )
    _, other_unread, _ = await repository.list_direct_feed(
        user_id=other_user_id,
        agency_id=agency_id,
        limit=10,
    )
    assert owner_items[0].is_read is True
    assert owner_unread == 0
    assert other_unread == 1


@pytest.mark.asyncio
async def test_invalid_feed_cursor_fails_closed(db_session) -> None:
    with pytest.raises(ValueError, match="invalid notification cursor"):
        await NotificationRepository(db_session).list_direct_feed(
            user_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            cursor="not-a-cursor",
        )


@pytest.mark.asyncio
async def test_direct_notification_can_be_read_without_an_agency_bypass(
    db_session,
) -> None:
    repository = NotificationRepository(db_session)
    owner_id = uuid.uuid4()
    notification = await repository.create(
        agency_id=uuid.uuid4(),
        user_id=owner_id,
        type="email_ai_attention",
        title="Owner only",
        message="Owner only.",
    )
    await db_session.flush()

    marked = await repository.mark_read(
        notification_id=notification.id,
        agency_id=None,
        user_id=owner_id,
    )
    assert marked.is_read is True


@pytest.mark.asyncio
async def test_direct_feed_and_read_actions_reject_a_users_former_agency(
    db_session,
) -> None:
    repository = NotificationRepository(db_session)
    current_agency_id = uuid.uuid4()
    former_agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    current = await repository.create(
        agency_id=current_agency_id,
        user_id=owner_id,
        type="email_ai_attention",
        title="Current agency",
        message="Visible.",
    )
    former = await repository.create(
        agency_id=former_agency_id,
        user_id=owner_id,
        type="email_ai_attention",
        title="Former agency",
        message="Must stay hidden.",
    )
    await db_session.flush()

    items, unread_count, _ = await repository.list_direct_feed(
        user_id=owner_id,
        agency_id=current_agency_id,
        limit=10,
    )
    assert [item.id for item in items] == [current.id]
    assert unread_count == 1
    assert (
        await repository.mark_all_direct_read(
            user_id=owner_id,
            agency_id=current_agency_id,
        )
        == 1
    )
    await db_session.refresh(former)
    assert former.is_read is False
    with pytest.raises(EntityNotFoundError):
        await repository.mark_read(
            notification_id=former.id,
            agency_id=current_agency_id,
            user_id=owner_id,
        )
