from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.application.mobile.announcement_notification_status import (
    AnnouncementDeviceDeliveryCounts,
    AnnouncementNotificationStatus,
    AnnouncementRecipientCounts,
)
from app.domain.entities.entities import UserRole
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import gc_app_content as routes
from app.presentation.api.v1.schemas.announcement_notification_status import (
    AnnouncementNotificationStatusResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.middleware.error_handler import register_exception_handlers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,provider,expected",
    [
        (True, "expo", True),
        (True, "fcm", True),
        (True, "disabled", False),
        (False, "expo", False),
        (False, "fcm", False),
    ],
)
async def test_notification_status_response_checks_runtime_provider_and_remains_read_only(
    enabled, provider, expected
) -> None:
    agency_id, group_id, access_id, announcement_id = [uuid.uuid4() for _ in range(4)]
    access = SimpleNamespace(id=access_id, agency_id=agency_id, group_id=group_id)
    summary = AnnouncementNotificationStatus(
        announcement_id,
        expected,
        AnnouncementRecipientCounts(total=4, queued=1, sent=1, failed=1, unknown=1),
        AnnouncementDeviceDeliveryCounts(
            total=5, provider_accepted=2, unknown=1, delivered=1, retry=1
        ),
        [],
        datetime.now(tz=UTC),
    )
    report = AsyncMock(return_value=summary)
    session = MagicMock()
    with (
        patch.object(
            routes, "_admin_access_context", AsyncMock(return_value=(access, SimpleNamespace()))
        ),
        patch.object(routes, "_get_announcement", AsyncMock()),
        patch.object(
            routes,
            "get_settings",
            return_value=SimpleNamespace(
                mobile=SimpleNamespace(enabled=enabled, push_provider=provider)
            ),
        ),
        patch.object(routes, "announcement_notification_status", report),
    ):
        response = await routes.get_announcement_notification_status(
            group_id,
            announcement_id,
            current_user=SimpleNamespace(role=UserRole.AGENCY_ADMIN, agency_id=agency_id),
            session=session,
        )
    assert response.provider_enabled is expected
    assert response.recipient_counts.total == 4
    assert response.recipient_counts.failed == 1
    assert response.recipient_counts.unknown == 1
    assert response.device_delivery_counts.total == 5
    assert response.device_delivery_counts.provider_accepted == 2
    assert response.device_delivery_counts.unknown == 1
    assert response.device_delivery_counts.delivered == 1
    serialized = response.model_dump(mode="json")
    assert serialized["recipient_counts"]["unknown"] == 1
    assert serialized["device_delivery_counts"]["provider_accepted"] == 2
    assert serialized["device_delivery_counts"]["unknown"] == 1
    report.assert_awaited_once_with(
        session,
        agency_id=agency_id,
        group_id=group_id,
        access_id=access_id,
        announcement_id=announcement_id,
        provider_enabled=expected,
    )
    session.commit.assert_not_called()
    session.flush.assert_not_called()


def test_additive_fcm_status_fields_default_to_zero_for_existing_status_payloads() -> None:
    response = AnnouncementNotificationStatusResponse.model_validate(
        {
            "announcement_id": uuid.uuid4(),
            "provider_enabled": False,
            "recipient_counts": {"total": 1, "queued": 1},
            "device_delivery_counts": {"total": 1, "receipt_pending": 1},
            "checked_at": datetime.now(tz=UTC),
        }
    )
    assert response.recipient_counts.unknown == 0
    assert response.device_delivery_counts.provider_accepted == 0
    assert response.device_delivery_counts.unknown == 0
    assert response.device_delivery_counts.receipt_pending == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR, UserRole.CLIENT_MANAGER]
)
async def test_notification_diagnostics_rejects_unauthorized_roles_before_querying(role) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(routes.router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=role)
    database = MagicMock()
    app.dependency_overrides[get_db_session] = lambda: database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/groups/{uuid.uuid4()}/announcements/{uuid.uuid4()}/notification-status"
        )
    assert response.status_code == 403
    database.execute.assert_not_called()


@pytest.mark.asyncio
async def test_notification_diagnostics_keeps_tenant_and_announcement_scope() -> None:
    agency_id, group_id, announcement_id = [uuid.uuid4() for _ in range(3)]
    user = SimpleNamespace(role=UserRole.AGENCY_MANAGER, agency_id=agency_id)
    database = MagicMock(execute=AsyncMock())
    # Use the actual scope helper: a caller-provided foreign agency fails
    # before any query or summary is allowed.
    with pytest.raises(routes.HTTPException) as denied:
        await routes.get_announcement_notification_status(
            group_id, announcement_id, agency_id=uuid.uuid4(), current_user=user, session=database
        )
    assert denied.value.status_code == 403
    database.execute.assert_not_awaited()
    access = SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id, group_id=group_id)
    access_result, missing_announcement = MagicMock(), MagicMock()
    access_result.first.return_value = (access, SimpleNamespace())
    missing_announcement.scalar_one_or_none.return_value = None
    database.execute.side_effect = [access_result, missing_announcement]
    with pytest.raises(routes.HTTPException) as missing:
        await routes.get_announcement_notification_status(
            group_id, announcement_id, current_user=user, session=database
        )
    assert missing.value.status_code == 404
    statement = database.execute.await_args.args[0]
    parameters = statement.compile().params
    assert announcement_id in parameters.values()
    assert agency_id in parameters.values()
    assert group_id in parameters.values()
    assert access.id in parameters.values()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,id_argument,getter,responder",
    [
        ("announcement", "announcement_id", "_get_announcement", "_announcement_response"),
        ("common_document", "document_id", "_get_common_document", "_common_document_response"),
        ("itinerary", "version_id", "_get_itinerary", "_itinerary_response"),
    ],
)
async def test_unpublishing_content_emits_delete_and_preserves_access_generation(
    kind, id_argument, getter, responder
) -> None:
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        access_generation=7,
        itinerary_version=1,
        announcement_version=1,
        common_document_version=1,
        manifest_version=2,
        revision=3,
    )
    item = SimpleNamespace(id=uuid.uuid4(), status="published")
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    journal = AsyncMock()
    cancel = AsyncMock()
    with (
        patch.object(
            routes, "_admin_access_context", AsyncMock(return_value=(access, SimpleNamespace()))
        ),
        patch.object(routes, getter, AsyncMock(return_value=item)),
        patch.object(
            routes,
            responder,
            AsyncMock(return_value={}) if kind == "itinerary" else MagicMock(return_value={}),
        ),
        patch.object(routes, "append_mobile_sync_change", journal),
        patch.object(routes, "cancel_announcement_notifications", cancel),
        patch.object(routes, "_content_audit", AsyncMock()),
    ):
        await getattr(routes, f"unpublish_{kind}")(
            group_id=access.group_id,
            **{id_argument: item.id},
            request=request,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=MagicMock(),
        )
    assert journal.await_args.kwargs["operation"] == "delete"
    assert journal.await_args.kwargs["entity_type"] == kind
    assert item.status == "retired"
    assert access.access_generation == 7
    assert access.manifest_version == 3
    if kind == "announcement":
        cancel.assert_awaited_once()
