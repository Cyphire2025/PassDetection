"""Bounded personal feed parity and source projection, without notification writes."""

import json
import uuid

import pytest
from sqlalchemy import event, func, select, update

from app.application.mcp.notification_reads import MCPNotificationReadService
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import NotificationModel, UserModel
from app.infrastructure.repositories.notification_projection_repository import (
    NotificationProjectionLimitError,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.notifications import notification_feed
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.mcp_notification_fixtures import seed_notifications


@pytest.fixture
async def notifications(operations_fixture):
    f = operations_fixture
    data = await seed_notifications(f[0], f[2].id)
    await f[0].commit()
    return f, data


def reader(f):
    return MCPNotificationReadService(f[0], cursor_secret=f[1].app_secret_key, namespace="personal-notifications")


async def test_personal_scope_website_parity_even_without_agency_and_no_effects(notifications):
    f, data = notifications
    assert f[2].agency_id is None
    result = await reader(f).list_personal(f[2].id)
    actor = await UserRepository(f[0]).get_by_id(f[2].id)
    web = await notification_feed(actor, f[0], False, None, None, 30)
    expected = web.model_dump(mode="json")
    for actual, canonical in zip(result["items"], expected["items"], strict=True):
        canonical["created_at"] = canonical["created_at"].replace("Z", "+00:00")
        if canonical["read_at"]:
            canonical["read_at"] = canonical["read_at"].replace("Z", "+00:00")
        for key in canonical.keys() - {"metadata"}:
            assert actual[key] == canonical[key]
        assert actual["metadata"] == {key: canonical["metadata"][key] for key in ("provider", "account_email", "group_name")}
    assert [row["id"] for row in result["items"]] == [str(row.id) for row in reversed(data.rows[:3])]
    assert result["unread_count"] == web.unread_count == 2
    assert result["notifications_acknowledged"] == 0 and result["content_trust"] == "untrusted_business_data"
    assert "PRIVATE-NOTIFICATION-SENTINEL" not in json.dumps(result)
    assert await f[0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    assert list((await f[0].scalars(select(NotificationModel.is_read).order_by(NotificationModel.id))).all()) == [False, True, False, False, False]


async def test_keyset_uuid_tie_filter_counts_and_cursor_scope(notifications):
    f, _data = notifications
    first = await reader(f).list_personal(f[2].id, page_size=1)
    second = await reader(f).list_personal(f[2].id, page_size=1, cursor=first["next_cursor"])
    third = await reader(f).list_personal(f[2].id, page_size=1, cursor=second["next_cursor"])
    assert len({page["items"][0]["id"] for page in (first, second, third)}) == 3
    assert third["next_cursor"] is None and third["completeness"] == "complete"
    for kwargs in ({"page_size": 2}, {"page_size": 1, "unread_only": True}, {"page_size": 1, "priority": "high"}):
        with pytest.raises(ValueError):
            await reader(f).list_personal(f[2].id, cursor=first["next_cursor"], **kwargs)
    with pytest.raises(ValueError):
        await reader(f).list_personal(f[2].id, page_size=1, cursor=first["next_cursor"] + "x")
    filtered = await reader(f).list_personal(f[2].id, priority="normal")
    assert len(filtered["items"]) == 1 and filtered["unread_count"] == 2
    unread = await reader(f).list_personal(f[2].id, unread_only=True)
    assert len(unread["items"]) == 2 and not any(row["is_read"] for row in unread["items"])


async def test_scalar_projection_never_hydrates_large_unknown_metadata(notifications):
    f, data = notifications
    await f[0].execute(update(NotificationModel).where(NotificationModel.id == data.rows[2].id)
        .values(metadata_json={"private": "x" * (2 * 1024 * 1024), "provider": {"not": "text"}, "group_name": 7}))
    await f[0].commit()
    statements = []
    def capture(_c, _cursor, sql, _params, _context, _many):
        statements.append(sql.lower())
    def forbidden(*_args):
        raise AssertionError("Personal feed hydrated an ORM notification")
    engine = f[0].bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    event.listen(NotificationModel, "load", forbidden)
    event.listen(NotificationModel, "refresh", forbidden)
    try:
        result = await reader(f).list_personal(f[2].id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        event.remove(NotificationModel, "load", forbidden)
        event.remove(NotificationModel, "refresh", forbidden)
    assert result["items"][0]["metadata"] == {}
    assert len(statements) == 4
    projection = statements[2].split("\nfrom")[0]
    assert "substr(" in projection and " as metadata_provider" in projection
    assert " notifications.metadata," not in projection and "dedupe_key" not in projection
    assert "limit" in statements[2]


@pytest.mark.parametrize("field,value", [("message", "x" * 4097), ("title", "x" * 256),
    ("metadata_json", {"provider": "x" * 33}), ("metadata_json", {"account_email": "x" * 321})])
async def test_oversized_field_fails_explicitly_without_partial_page(notifications, field, value):
    f, data = notifications
    await f[0].execute(update(NotificationModel).where(NotificationModel.id == data.rows[2].id).values(**{field: value}))
    with pytest.raises(NotificationProjectionLimitError):
        await reader(f).list_personal(f[2].id)


async def test_unicode_page_byte_budget_and_smaller_page_recovery(notifications):
    f, data = notifications
    for _ in range(17):
        f[0].add(NotificationModel(id=uuid.uuid4(), agency_id=data.agencies[0].id, user_id=f[2].id,
            type="synthetic", title="Bounded Unicode", message="🙂" * 4096,
            created_at=data.rows[0].created_at))
    await f[0].flush()
    with pytest.raises(NotificationProjectionLimitError):
        await reader(f).list_personal(f[2].id)
    result = await reader(f).list_personal(f[2].id, page_size=1)
    assert result["has_more"] and len(json.dumps(result, ensure_ascii=False).encode()) < 256 * 1024


@pytest.mark.parametrize("kwargs", [{"page_size": 0}, {"page_size": 101}, {"page_size": True}, {"priority": "all"}, {"unread_only": 1}])
async def test_input_bounds(notifications, kwargs):
    f, _ = notifications
    with pytest.raises(ValueError):
        await reader(f).list_personal(f[2].id, **kwargs)


async def test_cursor_cannot_cross_actor(notifications):
    f, data = notifications
    first = await reader(f).list_personal(f[2].id, page_size=1)
    await f[0].execute(update(UserModel).where(UserModel.id == data.other.id).values(role="super_admin"))
    with pytest.raises(ValueError):
        await reader(f).list_personal(data.other.id, page_size=1, cursor=first["next_cursor"])
