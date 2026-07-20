from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.admin import (
    _WhatsAppPurgeCounts,
    delete_manager,
    purge_passport_data,
)
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
) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(scalar_value=manager),
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
                _Result(scalar_values=[group_id]),
                _Result(rows=[submission]),
            ]
        )
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
    storage = SimpleNamespace(delete_files=AsyncMock(return_value=4))

    with (
        patch(
            "app.presentation.api.v1.routes.admin.MinioStorageRepository",
            return_value=storage,
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
        ]
    )
    assert response.deleted_storage_objects == 4
    session.delete.assert_awaited_once_with(manager)
    session.flush.assert_awaited_once_with()


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
    storage = SimpleNamespace(delete_files=AsyncMock(return_value=4))

    with (
        patch(
            "app.presentation.api.v1.routes.admin.MinioStorageRepository",
            return_value=storage,
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
    ):
        response = await purge_passport_data(
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    storage.delete_files.assert_awaited_once_with(
        [
            "front/original.jpg",
            "front/thumbnail.jpg",
            "back/original.jpg",
            "visa-photo/original.jpg",
        ]
    )
    assert response.deleted_storage_objects == 4


@pytest.mark.asyncio
async def test_agency_purge_scopes_submissions_through_authorized_groups() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session = _session_for_global_purge(
        group_id=group_id,
        submission=_submission_row(),
    )
    storage = SimpleNamespace(delete_files=AsyncMock(return_value=4))

    with (
        patch(
            "app.presentation.api.v1.routes.admin.MinioStorageRepository",
            return_value=storage,
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
    ):
        await purge_passport_data(
            current_user=_agency_admin(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    submission_query = session.execute.await_args_list[3].args[0]
    assert "passport_submissions.group_id IN" in str(submission_query)
    assert group_id in next(iter(submission_query.compile().params.values()))


@pytest.mark.asyncio
async def test_global_purge_does_not_delete_database_rows_after_storage_failure() -> None:
    session = _session_for_global_purge(
        group_id=uuid.uuid4(),
        submission=_submission_row(),
    )
    storage = SimpleNamespace(
        delete_files=AsyncMock(side_effect=StorageError("storage unavailable"))
    )
    delete_entity_rows = AsyncMock()
    delete_by_ids = AsyncMock()
    delete_whatsapp_data = AsyncMock()
    audit_record = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.admin.MinioStorageRepository",
            return_value=storage,
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
        pytest.raises(StorageError, match="storage unavailable"),
    ):
        await purge_passport_data(
            current_user=_super_admin(),
            session=session,  # type: ignore[arg-type]
        )

    delete_entity_rows.assert_not_awaited()
    delete_by_ids.assert_not_awaited()
    delete_whatsapp_data.assert_not_awaited()
    audit_record.assert_not_awaited()
