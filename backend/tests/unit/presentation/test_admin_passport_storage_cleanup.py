from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.presentation.api.v1.routes.admin import (
    _WhatsAppPurgeCounts,
    delete_manager,
    purge_passport_data,
)
from app.presentation.api.v1.routes.admin import router as admin_router
from app.presentation.api.v1.schemas.operations_schemas import DeleteManagerRequest


class _Result:
    def __init__(
        self,
        *,
        scalar_value: object | None = None,
        scalar_values: list[object] | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._scalar_value = scalar_value
        self._scalar_values = scalar_values or []
        self._rows = rows or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        return self._scalar_value

    def scalars(self) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self._scalar_values)

    def all(self) -> list[object]:
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


def _agency_admin(agency_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="agency-admin@example.com",
        hashed_password="unused",
        full_name="Agency Admin",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
    )


def test_platform_policy_and_passport_purge_mutations_require_csrf_and_step_up() -> None:
    expected = {
        ("/settings", "PUT"),
        ("/groups/{group_id}/passport-retention", "PUT"),
        ("/passport-data", "DELETE"),
    }

    for path, method in expected:
        route = next(
            route
            for route in admin_router.routes
            if route.path == path and method in route.methods
        )
        dependencies = {
            dependency.call.__name__ for dependency in route.dependant.dependencies
        }
        assert "require_cookie_csrf" in dependencies, (path, method)
        assert "require_recent_mfa" in dependencies, (path, method)


def _submission_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        image_s3_key="front/original.jpg",
        thumbnail_s3_key="front/thumbnail.jpg",
        passport_back_s3_key="back/original.jpg",
        passport_photo_s3_key="visa-photo/original.jpg",
    )


def _session_for_manager_deletion(
    *,
    manager: SimpleNamespace,
    group_id: uuid.UUID,
    submission: SimpleNamespace,
    email_connection_count: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(scalar_value=manager),
                _Result(scalar_value=email_connection_count),
                _Result(scalar_values=[group_id]),
                _Result(rows=[submission]),
            ]
        ),
        delete=AsyncMock(),
        flush=AsyncMock(),
    )


def _session_for_global_purge(
    *,
    group_id: uuid.UUID,
    submission: SimpleNamespace,
) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(),  # WhatsApp group rows locked for the purge.
                _Result(scalar_value=0),  # No provider request is processing.
                _Result(scalar_value=0),  # No target group is under legal hold.
                _Result(scalar_values=[group_id]),
                _Result(rows=[submission]),
            ]
        ),
        add=Mock(),
        commit=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_manager_owned_data_deletion_removes_every_passport_object() -> None:
    agency_id = uuid.uuid4()
    manager = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        email="manager@example.com",
        full_name="Trip Manager",
    )
    group_id = uuid.uuid4()
    submission = _submission_row()
    session = _session_for_manager_deletion(
        manager=manager,
        group_id=group_id,
        submission=submission,
    )
    derived_key = "passport-crops/manager/front/1.jpg"
    edit_source_key = "passport-edits/manager/photo/1.jpg"
    storage = SimpleNamespace(delete_files=AsyncMock(return_value=6))

    with (
        patch(
            "app.presentation.api.v1.routes.admin.MinioStorageRepository",
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
        patch(
            "app.presentation.api.v1.routes.admin._delete_entity_rows",
            AsyncMock(side_effect=[1, 2]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_by_ids",
            AsyncMock(side_effect=[1, 1, 1]),
        ),
        patch.object(
            AuditLogRepository,
            "record",
            AsyncMock(return_value=None),
        ),
    ):
        response = await delete_manager(
            manager_id=manager.id,
            body=DeleteManagerRequest(delete_owned_data=True),
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    storage.delete_files.assert_awaited_once_with(
        [
            "front/original.jpg",
            "front/thumbnail.jpg",
            "back/original.jpg",
            "visa-photo/original.jpg",
            derived_key,
            edit_source_key,
        ]
    )
    assert response.deleted_storage_objects == 6
    session.delete.assert_awaited_once_with(manager)
    session.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_manager_with_an_owned_mailbox_is_disabled_instead_of_hard_deleted() -> None:
    manager = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        email="manager@example.com",
        full_name="Trip Manager",
        hashed_password="existing-password-hash",
        is_active=True,
        deleted_at=None,
        updated_at=None,
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(scalar_value=manager),
                _Result(scalar_value=1),
                _Result(),
            ]
        ),
        delete=AsyncMock(),
        flush=AsyncMock(),
    )

    with (
        patch.object(AuditLogRepository, "record", AsyncMock(return_value=None)),
        patch(
            "app.presentation.api.v1.routes.admin.hash_password",
            return_value="revoked-password-hash",
        ),
    ):
        response = await delete_manager(
            manager_id=manager.id,
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert response.deleted_manager_id == manager.id
    session.delete.assert_not_awaited()
    assert manager.is_active is False
    assert manager.deleted_at is not None
    assert manager.email == f"deleted-{manager.id}@deleted.invalid"
    assert manager.hashed_password == "revoked-password-hash"
    update_statement = session.execute.await_args_list[2].args[0]
    assert "UPDATE email_connections" in str(update_statement)
    assert "owner_user_id" in str(update_statement)


@pytest.mark.asyncio
async def test_manager_deletion_does_not_mutate_database_after_storage_failure() -> None:
    manager = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        email="manager@example.com",
        full_name="Trip Manager",
    )
    session = _session_for_manager_deletion(
        manager=manager,
        group_id=uuid.uuid4(),
        submission=_submission_row(),
    )
    storage = SimpleNamespace(
        delete_files=AsyncMock(side_effect=StorageError("storage unavailable"))
    )
    delete_entity_rows = AsyncMock()
    delete_by_ids = AsyncMock()
    audit_record = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.admin.MinioStorageRepository",
            return_value=storage,
        ),
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=["passport-crops/manager/front/1.jpg"]),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=["passport-edits/manager/photo/1.jpg"]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_entity_rows",
            delete_entity_rows,
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_by_ids",
            delete_by_ids,
        ),
        patch.object(AuditLogRepository, "record", audit_record),
        pytest.raises(StorageError, match="storage unavailable"),
    ):
        await delete_manager(
            manager_id=manager.id,
            body=DeleteManagerRequest(delete_owned_data=True),
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    delete_entity_rows.assert_not_awaited()
    delete_by_ids.assert_not_awaited()
    audit_record.assert_not_awaited()
    session.delete.assert_not_awaited()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_passport_data_purge_removes_every_passport_object() -> None:
    group_id = uuid.uuid4()
    submission = _submission_row()
    session = _session_for_global_purge(
        group_id=group_id,
        submission=submission,
    )
    derived_key = "passport-crops/global/photo/1.jpg"
    edit_source_key = "passport-edits/global/photo/1.jpg"

    with (
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
        patch(
            "app.presentation.api.v1.routes.admin._delete_entity_rows",
            AsyncMock(side_effect=[1, 2]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_by_ids",
            AsyncMock(side_effect=[1, 1, 1]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_whatsapp_broadcast_data",
            AsyncMock(
                return_value=_WhatsAppPurgeCounts(
                    broadcast_groups=0,
                    recipients=0,
                    rejected_contacts=0,
                    support_contacts=0,
                    message_logs=0,
                    delivery_states=0,
                )
            ),
        ),
        patch.object(
            AuditLogRepository,
            "record",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.admin.process_storage_cleanup_job",
            AsyncMock(
                return_value=SimpleNamespace(completed=True, deleted_count=6)
            ),
        ),
    ):
        response = await purge_passport_data(
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert response.deleted_storage_objects == 6
    assert response.storage_cleanup_deferred is False
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_agency_purge_scopes_submissions_through_authorized_groups() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session = _session_for_global_purge(
        group_id=group_id,
        submission=_submission_row(),
    )

    with (
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_entity_rows",
            AsyncMock(side_effect=[0, 0]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_by_ids",
            AsyncMock(side_effect=[1, 1, 1]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_whatsapp_broadcast_data",
            AsyncMock(
                return_value=_WhatsAppPurgeCounts(
                    broadcast_groups=0,
                    recipients=0,
                    rejected_contacts=0,
                    support_contacts=0,
                    message_logs=0,
                    delivery_states=0,
                )
            ),
        ),
        patch.object(
            AuditLogRepository,
            "record",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.admin.process_storage_cleanup_job",
            AsyncMock(
                return_value=SimpleNamespace(completed=True, deleted_count=4)
            ),
        ),
    ):
        await purge_passport_data(
            current_user=_agency_admin(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    submission_query = session.execute.await_args_list[4].args[0]
    assert "passport_submissions.group_id IN" in str(submission_query)
    assert group_id in next(iter(submission_query.compile().params.values()))


@pytest.mark.asyncio
async def test_global_purge_commits_rows_and_defers_cleanup_after_storage_failure() -> None:
    session = _session_for_global_purge(
        group_id=uuid.uuid4(),
        submission=_submission_row(),
    )
    delete_entity_rows = AsyncMock(side_effect=[1, 2])
    delete_by_ids = AsyncMock(side_effect=[1, 1, 1])
    delete_whatsapp_data = AsyncMock(
        return_value=_WhatsAppPurgeCounts(
            broadcast_groups=0,
            recipients=0,
            rejected_contacts=0,
            support_contacts=0,
            message_logs=0,
            delivery_states=0,
        )
    )
    audit_record = AsyncMock()

    with (
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=["passport-crops/global/photo/1.jpg"]),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=["passport-edits/global/photo/1.jpg"]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_entity_rows",
            delete_entity_rows,
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_by_ids",
            delete_by_ids,
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_whatsapp_broadcast_data",
            delete_whatsapp_data,
        ),
        patch.object(AuditLogRepository, "record", audit_record),
        patch(
            "app.presentation.api.v1.routes.admin.process_storage_cleanup_job",
            AsyncMock(side_effect=StorageError("storage unavailable")),
        ),
    ):
        response = await purge_passport_data(
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert delete_entity_rows.await_count == 2
    assert delete_by_ids.await_count == 3
    delete_whatsapp_data.assert_awaited_once()
    audit_record.assert_awaited_once()
    session.commit.assert_awaited_once_with()
    assert response.deleted_storage_objects == 0
    assert response.storage_cleanup_deferred is True


@pytest.mark.asyncio
async def test_global_purge_stops_before_deletion_when_a_legal_hold_exists() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(),
                _Result(scalar_value=0),
                _Result(scalar_value=1),
            ]
        ),
        add=Mock(),
        commit=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await purge_passport_data(
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_purge_never_starts_object_cleanup_when_database_commit_fails() -> None:
    session = _session_for_global_purge(
        group_id=uuid.uuid4(),
        submission=_submission_row(),
    )
    session.commit.side_effect = RuntimeError("commit failed")
    process_cleanup = AsyncMock()

    with (
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_entity_rows",
            AsyncMock(side_effect=[0, 0]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_by_ids",
            AsyncMock(side_effect=[1, 1, 1]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_whatsapp_broadcast_data",
            AsyncMock(return_value=_WhatsAppPurgeCounts(0, 0, 0, 0, 0, 0)),
        ),
        patch.object(AuditLogRepository, "record", AsyncMock(return_value=None)),
        patch(
            "app.presentation.api.v1.routes.admin.process_storage_cleanup_job",
            process_cleanup,
        ),
        pytest.raises(RuntimeError, match="commit failed"),
    ):
        await purge_passport_data(
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    process_cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_purge_stops_before_row_deletion_when_tombstone_staging_fails() -> None:
    session = _session_for_global_purge(
        group_id=uuid.uuid4(),
        submission=_submission_row(),
    )
    delete_entity_rows = AsyncMock()
    delete_by_ids = AsyncMock()

    with (
        patch.object(
            PassportImageCropRepository,
            "derived_storage_keys",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            PassportImageCropRepository,
            "edit_storage_keys",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.presentation.api.v1.routes.admin.stage_storage_cleanup_jobs",
            side_effect=RuntimeError("tombstone unavailable"),
        ),
        patch(
            "app.presentation.api.v1.routes.admin._delete_entity_rows",
            delete_entity_rows,
        ),
        patch("app.presentation.api.v1.routes.admin._delete_by_ids", delete_by_ids),
        pytest.raises(RuntimeError, match="tombstone unavailable"),
    ):
        await purge_passport_data(
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    delete_entity_rows.assert_not_awaited()
    delete_by_ids.assert_not_awaited()
    session.commit.assert_not_awaited()
