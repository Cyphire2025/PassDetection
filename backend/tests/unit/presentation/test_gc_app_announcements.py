from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.presentation.api.v1.routes.gc_app_content import (
    delete_announcement,
    list_announcements,
)


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalars(self) -> _Result:
        return self

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._value)

    def all(self):  # type: ignore[no-untyped-def]
        return self._value


def _request() -> Request:
    return Request({"type": "http", "method": "DELETE", "path": "/", "headers": []})


@pytest.mark.asyncio
async def test_announcement_list_excludes_retired_and_revoked_history() -> None:
    access = SimpleNamespace(id=uuid.uuid4())
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result([])))

    with patch(
        "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
        new=AsyncMock(return_value=(access, SimpleNamespace())),
    ):
        response = await list_announcements(
            group_id=uuid.uuid4(),
            agency_id=None,
            current_user=SimpleNamespace(),
            session=session,  # type: ignore[arg-type]
        )

    assert response == []
    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "gc_announcements.status IN ('draft', 'published')" in sql


@pytest.mark.asyncio
async def test_deleting_published_announcement_cancels_pending_notifications() -> None:
    group_id = uuid.uuid4()
    announcement_id = uuid.uuid4()
    user_id = uuid.uuid4()
    access = SimpleNamespace(
        id=uuid.uuid4(),
        announcement_version=4,
        manifest_version=8,
        revision=12,
        updated_by_user_id=None,
        updated_at=None,
    )
    announcement = SimpleNamespace(
        id=announcement_id,
        status="published",
        revoked_at=None,
        updated_at=None,
    )
    session = SimpleNamespace()
    cancel = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            new=AsyncMock(return_value=(access, SimpleNamespace())),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._get_announcement",
            new=AsyncMock(return_value=announcement),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.append_mobile_sync_change",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.cancel_announcement_notifications",
            new=cancel,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._content_audit",
            new=AsyncMock(),
        ),
    ):
        response = await delete_announcement(
            group_id=group_id,
            announcement_id=announcement_id,
            request=_request(),
            agency_id=None,
            current_user=SimpleNamespace(id=user_id),
            session=session,  # type: ignore[arg-type]
        )

    assert response.status_code == 204
    assert announcement.status == "revoked"
    assert access.announcement_version == 5
    cancel.assert_awaited_once()
    assert cancel.await_args.kwargs["announcement_id"] == announcement_id
