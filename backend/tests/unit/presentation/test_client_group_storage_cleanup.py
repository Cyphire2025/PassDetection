from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import ClientGroup
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import (
    ClientGroupRepository,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.presentation.api.v1.routes.client_groups import (
    permanently_delete_client_group,
)


def test_permanent_group_cleanup_includes_every_passport_image_variant() -> None:
    submissions = [
        SimpleNamespace(
            image_s3_key="front/original.jpg",
            thumbnail_s3_key="front/thumbnail.jpg",
            passport_back_s3_key="back/original.jpg",
            passport_photo_s3_key="visa/original.jpg",
        ),
        SimpleNamespace(
            image_s3_key="front/original.jpg",
            thumbnail_s3_key=None,
            passport_back_s3_key="back/second.jpg",
            passport_photo_s3_key=None,
        ),
    ]

    assert passport_storage_keys(submissions) == [
        "front/original.jpg",
        "front/thumbnail.jpg",
        "back/original.jpg",
        "visa/original.jpg",
        "back/second.jpg",
    ]


@pytest.mark.asyncio
async def test_data_removal_deletes_submissions_before_qualifier_rows() -> None:
    group = ClientGroup.create(
        name="Delete Group",
        token="delete-group-token",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        relation_with_qualifier_enabled=True,
    )
    group.archive()
    submission = SimpleNamespace(
        id=uuid.uuid4(),
        image_s3_key="front/original.jpg",
        thumbnail_s3_key="front/thumbnail.jpg",
        passport_back_s3_key="back/original.jpg",
        passport_photo_s3_key="visa/original.jpg",
    )
    execute_result = SimpleNamespace(
        all=lambda: [submission],
        scalar_one_or_none=lambda: None,
        rowcount=1,
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=execute_result),
    )
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        email="admin@example.com",
    )
    storage = SimpleNamespace(
        delete_files=AsyncMock(return_value=5),
    )
    derived_key = "passport-crops/group/front/1.jpg"
    edit_source_key = "passport-edits/group/photo/1.jpg"

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=group),
        ),
        patch.object(
            ClientGroupRepository,
            "update",
            AsyncMock(return_value=group),
        ),
        patch(
            "app.presentation.api.v1.routes.client_groups.AuthorizationPolicy.require_delete_data",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.client_groups.MinioStorageRepository",
            return_value=storage,
        ),
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=[derived_key]),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=[edit_source_key]),
        ),
        patch.object(
            AuditLogRepository,
            "record",
            AsyncMock(return_value=None),
        ),
    ):
        result = await permanently_delete_client_group(
            link_id=group.id,
            retain_records=False,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    storage.delete_files.assert_awaited_once_with(
        [
            "front/original.jpg",
            "front/thumbnail.jpg",
            "back/original.jpg",
            "visa/original.jpg",
            derived_key,
            edit_source_key,
        ]
    )
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    passport_delete = next(
        index
        for index, statement in enumerate(statements)
        if "DELETE FROM passport_submissions" in statement
    )
    qualifier_delete = next(
        index
        for index, statement in enumerate(statements)
        if "DELETE FROM qualifier_selections" in statement
    )
    assert passport_delete < qualifier_delete
    assert result["deleted_qualifier_selections"] == 1


@pytest.mark.asyncio
async def test_permanent_group_delete_blocks_active_roster_decisions() -> None:
    group = ClientGroup.create(
        name="Delete Group",
        token="delete-group-token",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
    )
    group.archive()
    active_resolution_result = SimpleNamespace(scalar_one_or_none=lambda: uuid.uuid4())
    session = SimpleNamespace(
        execute=AsyncMock(return_value=active_resolution_result),
    )
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        email="admin@example.com",
    )

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=group),
        ),
        patch(
            "app.presentation.api.v1.routes.client_groups.AuthorizationPolicy.require_delete_data",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.client_groups.MinioStorageRepository"
        ) as storage_factory,
        pytest.raises(HTTPException) as caught,
    ):
        await permanently_delete_client_group(
            link_id=group.id,
            retain_records=False,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 409
    assert "Restore all active replacement" in str(caught.value.detail)
    storage_factory.assert_not_called()
    assert session.execute.await_count == 1
