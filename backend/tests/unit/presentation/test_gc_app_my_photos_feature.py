from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.gc_app import (
    configure_gc_group_my_photos_feature,
    router,
)
from app.presentation.api.v1.schemas.gc_app_schemas import GCMyPhotosFeatureUpdateRequest


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _actor(agency_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
        email="admin@example.test",
    )


def _access(agency_id: uuid.UUID, group_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        is_enabled=True,
        passenger_access_enabled=True,
        revoked_at=None,
        access_generation=7,
        manifest_version=11,
        revision=5,
        updated_by_user_id=None,
        updated_at=datetime.now(tz=UTC),
    )


def test_my_photos_feature_toggle_route_is_registered() -> None:
    method_paths = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert ("PUT", "/groups/{group_id}/features/my-photos") in method_paths


@pytest.mark.asyncio
async def test_enabling_my_photos_creates_placeholder_and_journals_without_refencing() -> None:
    agency_id, group_id = uuid.uuid4(), uuid.uuid4()
    actor = _actor(agency_id)
    access = _access(agency_id, group_id)
    group = SimpleNamespace(status="active")
    response = SimpleNamespace(my_photos_enabled=True)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(None)),
        add=Mock(),
        flush=AsyncMock(),
    )

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app._get_group",
            new=AsyncMock(return_value=group),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app._get_group_access",
            new=AsyncMock(return_value=access),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app.append_mobile_sync_change",
            new=AsyncMock(),
        ) as append_change,
        patch(
            "app.presentation.api.v1.routes.gc_app._audit",
            new=AsyncMock(),
        ) as audit,
        patch(
            "app.presentation.api.v1.routes.gc_app._group_access_response",
            new=AsyncMock(return_value=response),
        ),
    ):
        result = await configure_gc_group_my_photos_feature(
            group_id=group_id,
            body=GCMyPhotosFeatureUpdateRequest(enabled=True, expected_revision=5),
            request=SimpleNamespace(),  # type: ignore[arg-type]
            current_user=actor,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    assert result is response
    gallery = session.add.call_args.args[0]
    assert gallery.agency_id == agency_id
    assert gallery.group_id == group_id
    assert gallery.gc_group_access_id == access.id
    assert gallery.feature_enabled is True
    assert gallery.status == "not_uploaded"
    assert access.access_generation == 7
    assert access.manifest_version == 12
    assert access.revision == 6
    append_change.assert_awaited_once()
    change_kwargs = append_change.await_args.kwargs
    assert change_kwargs["audience"] == "passenger"
    assert change_kwargs["entity_type"] == "my_photos_capability"
    assert change_kwargs["operation"] == "upsert"
    assert change_kwargs["version"] == 12
    assert change_kwargs["payload"] == {
        "resource_path": f"/api/v1/mobile/trips/{group_id}/my-photos"
    }
    assert audit.await_args.kwargs["action"] == "gc_app.my_photos_enabled"


@pytest.mark.asyncio
async def test_disabling_my_photos_is_optimistic_and_keeps_sessions_valid() -> None:
    agency_id, group_id = uuid.uuid4(), uuid.uuid4()
    actor = _actor(agency_id)
    access = _access(agency_id, group_id)
    gallery = SimpleNamespace(
        id=uuid.uuid4(),
        feature_enabled=True,
        updated_at=datetime.now(tz=UTC),
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(gallery)),
        add=Mock(),
        flush=AsyncMock(),
    )

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app._get_group",
            new=AsyncMock(return_value=SimpleNamespace(status="active")),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app._get_group_access",
            new=AsyncMock(return_value=access),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app.append_mobile_sync_change",
            new=AsyncMock(),
        ) as append_change,
        patch(
            "app.presentation.api.v1.routes.gc_app._audit",
            new=AsyncMock(),
        ) as audit,
        patch(
            "app.presentation.api.v1.routes.gc_app._group_access_response",
            new=AsyncMock(return_value=SimpleNamespace(my_photos_enabled=False)),
        ),
    ):
        await configure_gc_group_my_photos_feature(
            group_id=group_id,
            body=GCMyPhotosFeatureUpdateRequest(enabled=False, expected_revision=5),
            request=SimpleNamespace(),  # type: ignore[arg-type]
            current_user=actor,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    assert gallery.feature_enabled is False
    assert access.access_generation == 7
    assert access.manifest_version == 12
    assert access.revision == 6
    assert append_change.await_args.kwargs["operation"] == "upsert"
    assert audit.await_args.kwargs["action"] == "gc_app.my_photos_disabled"


@pytest.mark.asyncio
async def test_my_photos_toggle_rejects_stale_revision_before_writing() -> None:
    agency_id, group_id = uuid.uuid4(), uuid.uuid4()
    access = _access(agency_id, group_id)
    session = SimpleNamespace(execute=AsyncMock(), add=Mock(), flush=AsyncMock())

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app._get_group",
            new=AsyncMock(return_value=SimpleNamespace(status="active")),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app._get_group_access",
            new=AsyncMock(return_value=access),
        ),
        pytest.raises(HTTPException) as captured,
    ):
        await configure_gc_group_my_photos_feature(
            group_id=group_id,
            body=GCMyPhotosFeatureUpdateRequest(enabled=True, expected_revision=4),
            request=SimpleNamespace(),  # type: ignore[arg-type]
            current_user=_actor(agency_id),  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 409
    assert captured.value.detail == "GC App settings changed; refresh and retry"
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_my_photos_toggle_is_idempotent_without_version_or_journal_churn() -> None:
    agency_id, group_id = uuid.uuid4(), uuid.uuid4()
    actor = _actor(agency_id)
    access = _access(agency_id, group_id)
    gallery = SimpleNamespace(id=uuid.uuid4(), feature_enabled=True)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(gallery)),
        add=Mock(),
        flush=AsyncMock(),
    )

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app._get_group",
            new=AsyncMock(return_value=SimpleNamespace(status="active")),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app._get_group_access",
            new=AsyncMock(return_value=access),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app.append_mobile_sync_change",
            new=AsyncMock(),
        ) as append_change,
        patch(
            "app.presentation.api.v1.routes.gc_app._audit",
            new=AsyncMock(),
        ) as audit,
        patch(
            "app.presentation.api.v1.routes.gc_app._group_access_response",
            new=AsyncMock(return_value=SimpleNamespace(my_photos_enabled=True)),
        ),
    ):
        await configure_gc_group_my_photos_feature(
            group_id=group_id,
            body=GCMyPhotosFeatureUpdateRequest(enabled=True, expected_revision=5),
            request=SimpleNamespace(),  # type: ignore[arg-type]
            current_user=actor,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    assert access.access_generation == 7
    assert access.manifest_version == 11
    assert access.revision == 5
    session.flush.assert_not_awaited()
    append_change.assert_not_awaited()
    audit.assert_not_awaited()
