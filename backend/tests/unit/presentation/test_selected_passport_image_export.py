from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes import passports as passports_route
from app.presentation.api.v1.schemas.passport_schemas import (
    ExportSelectedPassportsRequest,
)


def _user(agency_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.test",
        hashed_password="hash",
        full_name="Admin",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
    )


def test_selected_image_export_route_contract() -> None:
    route = next(
        route
        for route in passports_route.router.routes
        if getattr(route, "endpoint", None)
        is passports_route.export_selected_passport_images_by_group
    )

    assert route.path == "/groups/{group_id}/export-images/selected"
    assert route.methods == {"POST"}


@pytest.mark.asyncio
async def test_selected_image_export_uses_full_group_naming_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    selected_id = uuid.uuid4()
    other_id = uuid.uuid4()
    group = SimpleNamespace(
        id=group_id,
        name="Vietnam 2026",
        staff_code_enabled=True,
        agent_employee_code_enabled=True,
    )
    selected = SimpleNamespace(id=selected_id)
    other = SimpleNamespace(id=other_id)
    current_submissions = [other, selected]
    authorize = AsyncMock()
    crop_metadata = {selected_id: {}}
    zones = {selected_id: "South", other_id: "North"}
    exporter = SimpleNamespace(
        export_group=AsyncMock(
            return_value=(io.BytesIO(b"zip-content"), 3, 1024)
        )
    )
    storage = object()

    monkeypatch.setattr(
        passports_route,
        "ClientGroupRepository",
        lambda session: SimpleNamespace(get_by_id=AsyncMock(return_value=group)),
    )
    monkeypatch.setattr(
        passports_route,
        "AuthorizationPolicy",
        lambda session: SimpleNamespace(require_export_data=authorize),
    )
    monkeypatch.setattr(
        passports_route,
        "_current_group_export_submissions",
        AsyncMock(return_value=current_submissions),
    )
    monkeypatch.setattr(
        passports_route,
        "PassportImageCropRepository",
        lambda session: SimpleNamespace(
            list_for_submissions=AsyncMock(return_value=crop_metadata)
        ),
    )
    monkeypatch.setattr(
        passports_route,
        "_export_zone_names",
        AsyncMock(return_value=zones),
    )
    monkeypatch.setattr(
        passports_route,
        "PassportImageZipExporter",
        lambda: exporter,
    )
    monkeypatch.setattr(
        passports_route,
        "MinioStorageRepository",
        lambda: storage,
    )

    response = await passports_route.export_selected_passport_images_by_group(
        group_id=group_id,
        body=ExportSelectedPassportsRequest(
            submission_ids=[selected_id, selected_id]
        ),
        current_user=_user(agency_id),
        session=AsyncMock(spec=AsyncSession),
    )
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())

    assert b"".join(chunks) == b"zip-content"
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-length"] == str(len(b"zip-content"))
    assert "Vietnam 2026_PASSPORT_IMAGES.zip" in response.headers[
        "content-disposition"
    ]
    authorize.assert_awaited_once()
    exporter.export_group.assert_awaited_once_with(
        [selected],
        group_name="Vietnam 2026",
        staff_code_enabled=True,
        agent_employee_code_enabled=True,
        storage=storage,
        crop_metadata=crop_metadata,
        zone_names=zones,
        namespace_submissions=current_submissions,
    )


@pytest.mark.asyncio
async def test_selected_image_export_rejects_ids_outside_the_current_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    current_id = uuid.uuid4()
    group = SimpleNamespace(
        id=group_id,
        name="Vietnam 2026",
        staff_code_enabled=False,
        agent_employee_code_enabled=False,
    )

    monkeypatch.setattr(
        passports_route,
        "ClientGroupRepository",
        lambda session: SimpleNamespace(get_by_id=AsyncMock(return_value=group)),
    )
    monkeypatch.setattr(
        passports_route,
        "AuthorizationPolicy",
        lambda session: SimpleNamespace(require_export_data=AsyncMock()),
    )
    monkeypatch.setattr(
        passports_route,
        "_current_group_export_submissions",
        AsyncMock(return_value=[SimpleNamespace(id=current_id)]),
    )

    with pytest.raises(HTTPException) as raised:
        await passports_route.export_selected_passport_images_by_group(
            group_id=group_id,
            body=ExportSelectedPassportsRequest(
                submission_ids=[uuid.uuid4()]
            ),
            current_user=_user(agency_id),
            session=AsyncMock(spec=AsyncSession),
        )

    assert raised.value.status_code == 404
    assert raised.value.detail == (
        "One or more selected passport submissions were not found in this group."
    )
