from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError, StorageError
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import (
    ClientGroupRepository,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.presentation.api.v1.routes.passports import (
    bulk_delete_passport_submissions,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsRequest,
)


class _Result:
    def __init__(
        self,
        *,
        rows: list[SimpleNamespace] | None = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self) -> list[SimpleNamespace]:
        return self._rows


def _super_admin() -> User:
    return User(
        id=uuid.uuid4(),
        email="root@example.com",
        hashed_password="unused",
        full_name="Root Admin",
        role=UserRole.SUPER_ADMIN,
        agency_id=None,
    )


def _submission_row(submission_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=submission_id,
        image_s3_key=f"front/{submission_id}.jpg",
        thumbnail_s3_key=f"thumbnail/{submission_id}.jpg",
        passport_back_s3_key=f"back/{submission_id}.jpg",
        passport_photo_s3_key=f"photo/{submission_id}.jpg",
    )


@pytest.mark.asyncio
async def test_bulk_delete_removes_all_selected_rows_and_stored_documents() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    submission_ids = [uuid.uuid4(), uuid.uuid4()]
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    events: list[str] = []

    async def commit() -> None:
        events.append("commit")

    async def delete_files(keys: list[str]) -> int:
        events.append("storage")
        return len(keys)

    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(rows=[_submission_row(item) for item in submission_ids]),
                _Result(rowcount=3),
                _Result(rowcount=2),
            ]
        ),
        commit=AsyncMock(side_effect=commit),
    )
    storage = SimpleNamespace(delete_files=AsyncMock(side_effect=delete_files))
    authorize = AsyncMock(return_value=None)
    audit = AsyncMock(return_value=None)
    derived_keys = [
        f"passport-crops/{submission_ids[0]}/front/1.jpg",
        f"passport-crops/{submission_ids[1]}/photo/2.jpg",
    ]
    edit_keys = [f"passport-edits/{submission_ids[0]}/photo/3.jpg"]

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=group),
        ),
        patch.object(
            AuthorizationPolicy,
            "require_delete_data",
            authorize,
        ),
        patch(
            "app.presentation.api.v1.routes.passports._active_roster_resolution_references",
            AsyncMock(return_value=set()),
        ),
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=derived_keys),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=edit_keys),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.MinioStorageRepository",
            return_value=storage,
        ),
        patch.object(AuditLogRepository, "record", audit),
    ):
        response = await bulk_delete_passport_submissions(
            group_id=group_id,
            body=BulkDeletePassportSubmissionsRequest(submission_ids=submission_ids),
            _csrf=None,
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    authorize.assert_awaited_once()
    assert authorize.await_args.kwargs["permanent"] is True
    storage.delete_files.assert_awaited_once_with(
        [
            f"front/{submission_ids[0]}.jpg",
            f"thumbnail/{submission_ids[0]}.jpg",
            f"back/{submission_ids[0]}.jpg",
            f"photo/{submission_ids[0]}.jpg",
            f"front/{submission_ids[1]}.jpg",
            f"thumbnail/{submission_ids[1]}.jpg",
            f"back/{submission_ids[1]}.jpg",
            f"photo/{submission_ids[1]}.jpg",
            *derived_keys,
            *edit_keys,
        ]
    )
    assert response.deleted_count == 2
    assert response.deleted_submission_ids == submission_ids
    assert response.deleted_storage_objects == 11
    assert response.deleted_notifications == 3
    assert response.storage_cleanup_deferred is False
    assert events == ["commit", "storage"]
    notification_delete = session.execute.await_args_list[1].args[0]
    notification_sql = str(notification_delete)
    assert "DELETE FROM notifications" in notification_sql
    assert "notifications.agency_id" in notification_sql
    assert "notifications.entity_type" in notification_sql
    assert "notifications.entity_id IN" in notification_sql
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "passport_submissions_bulk_deleted"
    assert audit.await_args.kwargs["metadata"]["deleted_count"] == 2
    assert audit.await_args.kwargs["metadata"]["deleted_notifications"] == 3
    assert audit.await_args.kwargs["metadata"]["storage_objects_scheduled_for_cleanup"] == 11


@pytest.mark.asyncio
async def test_bulk_delete_is_all_or_nothing_when_a_selection_is_missing() -> None:
    group_id = uuid.uuid4()
    submission_ids = [uuid.uuid4(), uuid.uuid4()]
    group = SimpleNamespace(id=group_id, agency_id=uuid.uuid4())
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_Result(rows=[_submission_row(submission_ids[0])]))
    )
    storage = SimpleNamespace(delete_files=AsyncMock())

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=group),
        ),
        patch.object(
            AuthorizationPolicy,
            "require_delete_data",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.passports._active_roster_resolution_references",
            AsyncMock(return_value=set()),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.MinioStorageRepository",
            return_value=storage,
        ),
        patch.object(AuditLogRepository, "record", AsyncMock()) as audit,
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_delete_passport_submissions(
            group_id=group_id,
            body=BulkDeletePassportSubmissionsRequest(submission_ids=submission_ids),
            _csrf=None,
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 404
    assert session.execute.await_count == 1
    storage.delete_files.assert_not_awaited()
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_delete_blocks_uploads_referenced_by_active_roster_decisions() -> None:
    group_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=uuid.uuid4())
    ordering: list[str] = []

    async def execute_locked_submission(_query: object) -> _Result:
        ordering.append("submission_locked")
        return _Result(rows=[_submission_row(submission_id)])

    async def protected_references(*_args: object, **_kwargs: object) -> set[uuid.UUID]:
        assert ordering == ["submission_locked"]
        ordering.append("references_checked")
        return {submission_id}

    session = SimpleNamespace(execute=AsyncMock(side_effect=execute_locked_submission))

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=group),
        ),
        patch.object(
            AuthorizationPolicy,
            "require_delete_data",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.passports._active_roster_resolution_references",
            AsyncMock(side_effect=protected_references),
        ),
        patch.object(AuditLogRepository, "record", AsyncMock()) as audit,
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_delete_passport_submissions(
            group_id=group_id,
            body=BulkDeletePassportSubmissionsRequest(submission_ids=[submission_id]),
            _csrf=None,
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 409
    assert "Restore that roster decision" in str(caught.value.detail)
    session.execute.assert_awaited_once()
    locked_submission_query = session.execute.await_args.args[0]
    assert locked_submission_query._for_update_arg is not None
    assert ordering == ["submission_locked", "references_checked"]
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_delete_enforces_permanent_data_delete_permission() -> None:
    group_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=uuid.uuid4())
    session = SimpleNamespace(execute=AsyncMock())

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=group),
        ),
        patch.object(
            AuthorizationPolicy,
            "require_delete_data",
            AsyncMock(side_effect=AuthorizationError("You cannot delete data for this group")),
        ),
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_delete_passport_submissions(
            group_id=group_id,
            body=BulkDeletePassportSubmissionsRequest(submission_ids=[uuid.uuid4()]),
            _csrf=None,
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 403
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_delete_reports_deferred_cleanup_after_storage_failure() -> None:
    group_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=uuid.uuid4())
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(rows=[_submission_row(submission_id)]),
                _Result(rowcount=1),
                _Result(rowcount=1),
            ]
        ),
        commit=AsyncMock(return_value=None),
    )
    storage = SimpleNamespace(
        delete_files=AsyncMock(side_effect=StorageError("storage unavailable"))
    )

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=group),
        ),
        patch.object(
            AuthorizationPolicy,
            "require_delete_data",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.passports._active_roster_resolution_references",
            AsyncMock(return_value=set()),
        ),
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=["passport-crops/derived.jpg"]),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.MinioStorageRepository",
            return_value=storage,
        ),
        patch.object(AuditLogRepository, "record", AsyncMock()) as audit,
    ):
        response = await bulk_delete_passport_submissions(
            group_id=group_id,
            body=BulkDeletePassportSubmissionsRequest(submission_ids=[submission_id]),
            _csrf=None,
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert session.execute.await_count == 3
    session.commit.assert_awaited_once_with()
    audit.assert_awaited_once()
    assert response.deleted_count == 1
    assert response.deleted_storage_objects == 0
    assert response.storage_cleanup_deferred is True


@pytest.mark.asyncio
async def test_bulk_delete_does_not_touch_storage_when_database_commit_fails() -> None:
    group_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=uuid.uuid4())
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(rows=[_submission_row(submission_id)]),
                _Result(rowcount=1),
                _Result(rowcount=1),
            ]
        ),
        commit=AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    storage = SimpleNamespace(delete_files=AsyncMock())

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=group),
        ),
        patch.object(
            AuthorizationPolicy,
            "require_delete_data",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.passports._active_roster_resolution_references",
            AsyncMock(return_value=set()),
        ),
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=["passport-crops/derived.jpg"]),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.MinioStorageRepository",
            return_value=storage,
        ),
        patch.object(AuditLogRepository, "record", AsyncMock()) as audit,
        pytest.raises(RuntimeError, match="database unavailable"),
    ):
        await bulk_delete_passport_submissions(
            group_id=group_id,
            body=BulkDeletePassportSubmissionsRequest(submission_ids=[submission_id]),
            _csrf=None,
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    audit.assert_awaited_once()
    session.commit.assert_awaited_once_with()
    storage.delete_files.assert_not_awaited()
