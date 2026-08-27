from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.application.platform_policies import PlatformPolicies
from app.application.security.destructive_mutation_policy import DestructiveMutationPolicy
from app.domain.entities.entities import ClientGroup
from app.domain.exceptions.exceptions import ConflictError, PassportLegalHoldError
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
from app.presentation.api.v1.routes.client_groups import router as client_group_router


def _mutation(group: ClientGroup) -> SimpleNamespace:
    return SimpleNamespace(
        group=group,
        action="client_group_permanent_delete",
        request_fingerprint="group-delete-fingerprint",
        target_count=0,
    )


def test_permanent_group_delete_requires_explicit_csrf_and_recent_mfa() -> None:
    route = next(
        route
        for route in client_group_router.routes
        if route.path == "/{link_id}/permanent" and "DELETE" in route.methods
    )
    dependencies = {dependency.call.__name__ for dependency in route.dependant.dependencies}
    assert "require_cookie_csrf" in dependencies
    assert "require_recent_mfa" in dependencies


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
        commit=AsyncMock(),
    )
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        email="admin@example.com",
    )
    derived_key = "passport-crops/group/front/1.jpg"
    edit_source_key = "passport-edits/group/photo/1.jpg"

    with (
        patch.object(
            DestructiveMutationPolicy,
            "require_group",
            AsyncMock(return_value=_mutation(group)),
        ),
        patch.object(
            ClientGroupRepository,
            "update",
            AsyncMock(return_value=group),
        ),
        patch(
            "app.presentation.api.v1.routes.client_groups.stage_storage_cleanup_jobs",
            return_value=(SimpleNamespace(object_count=6),),
        ) as stage_cleanup,
        patch(
            "app.presentation.api.v1.routes.client_groups.PlatformPolicyRepository.load",
            AsyncMock(return_value=PlatformPolicies(passport_data_retention_days=90)),
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

    stage_cleanup.assert_called_once_with(
        session,
        agency_id=group.agency_id,
        source="passport_submission_delete",
        context_id=f"group:{group.id}",
        storage_keys=[
            "front/original.jpg",
            "front/thumbnail.jpg",
            "back/original.jpg",
            "visa/original.jpg",
            derived_key,
            edit_source_key,
        ],
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
    assert result["deleted_storage_objects"] == 0
    assert result["storage_cleanup_deferred"] is True
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_group_delete_commit_failure_records_failure_and_keeps_cleanup_deferred() -> None:
    group = ClientGroup.create(
        name="Commit Failure Group",
        token="commit-failure-group-token",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
    )
    group.archive()
    submission = SimpleNamespace(
        id=uuid.uuid4(),
        image_s3_key="front/original.jpg",
        thumbnail_s3_key=None,
        passport_back_s3_key=None,
        passport_photo_s3_key=None,
    )
    execute_result = SimpleNamespace(
        all=lambda: [submission],
        scalar_one_or_none=lambda: None,
        rowcount=1,
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=execute_result),
        commit=AsyncMock(side_effect=RuntimeError("commit unavailable")),
    )
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        email="admin@example.com",
    )
    mutation = _mutation(group)
    cleanup_job = SimpleNamespace(id=uuid.uuid4(), object_count=1)
    record_failure = AsyncMock(return_value=True)

    with (
        patch.object(
            DestructiveMutationPolicy,
            "require_group",
            AsyncMock(return_value=mutation),
        ),
        patch.object(ClientGroupRepository, "update", AsyncMock(return_value=group)),
        patch(
            "app.presentation.api.v1.routes.client_groups.stage_storage_cleanup_jobs",
            return_value=(cleanup_job,),
        ),
        patch(
            "app.presentation.api.v1.routes.client_groups.PlatformPolicyRepository.load",
            AsyncMock(return_value=PlatformPolicies(passport_data_retention_days=90)),
        ),
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
        patch.object(AuditLogRepository, "record", AsyncMock(return_value=None)),
        patch(
            "app.presentation.api.v1.routes.client_groups.record_destructive_failure",
            record_failure,
        ),
        pytest.raises(RuntimeError, match="commit unavailable"),
    ):
        await permanently_delete_client_group(
            link_id=group.id,
            retain_records=False,
            current_user=current_user,
            session=session,
        )

    session.commit.assert_awaited_once_with()
    record_failure.assert_awaited_once()
    assert record_failure.await_args.args == (mutation,)
    assert record_failure.await_args.kwargs["error"].args == ("commit unavailable",)


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
        commit=AsyncMock(),
    )
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        email="admin@example.com",
    )

    with (
        patch.object(
            DestructiveMutationPolicy,
            "require_group",
            AsyncMock(return_value=_mutation(group)),
        ),
        patch.object(AuditLogRepository, "record", AsyncMock()) as audit,
        patch(
            "app.presentation.api.v1.routes.client_groups.stage_storage_cleanup_jobs"
        ) as storage_factory,
        pytest.raises(ConflictError) as caught,
    ):
        await permanently_delete_client_group(
            link_id=group.id,
            retain_records=False,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.code == "PASSPORT_ROSTER_DECISION_ACTIVE"
    assert "Restore all active replacement" in caught.value.message
    storage_factory.assert_not_called()
    assert session.execute.await_count == 1
    audit.assert_awaited_once()
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("retain_records", [False, True])
async def test_permanent_group_delete_cannot_bypass_legal_hold(
    retain_records: bool,
) -> None:
    group = ClientGroup.create(
        name="Held Delete Group",
        token="held-delete-group-token",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
    )
    group.archive()
    group.passport_legal_hold = True
    group.passport_legal_hold_reason = "Regulatory investigation"
    group.passport_legal_hold_set_at = group.closed_at
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        email="admin@example.com",
    )

    with (
        patch.object(
            DestructiveMutationPolicy,
            "require_group",
            AsyncMock(side_effect=PassportLegalHoldError()),
        ),
        patch(
            "app.presentation.api.v1.routes.client_groups.stage_storage_cleanup_jobs"
        ) as stage_cleanup,
        pytest.raises(PassportLegalHoldError) as caught,
    ):
        await permanently_delete_client_group(
            link_id=group.id,
            retain_records=retain_records,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.code == "PASSPORT_LEGAL_HOLD_ACTIVE"
    stage_cleanup.assert_not_called()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_permanent_group_delete_exact_retry_is_idempotent() -> None:
    group = ClientGroup.create(
        name="Already Deleted Group",
        token="already-deleted-group-token",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
    )
    group.archive()
    group.mark_deleted(
        passport_count=7,
        retain_records=True,
        passport_retention_days=90,
    )
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        email="admin@example.com",
    )

    with (
        patch.object(
            DestructiveMutationPolicy,
            "require_group",
            AsyncMock(return_value=_mutation(group)),
        ),
        patch.object(ClientGroupRepository, "update", AsyncMock()) as update_group,
        patch(
            "app.presentation.api.v1.routes.client_groups.stage_storage_cleanup_jobs"
        ) as stage_cleanup,
        patch.object(AuditLogRepository, "record", AsyncMock()) as audit,
    ):
        result = await permanently_delete_client_group(
            link_id=group.id,
            retain_records=True,
            current_user=current_user,
            session=session,
        )

    assert result["deleted"] is True
    assert result["retained_records"] is True
    assert result["historical_passport_count"] == 7
    assert result["deleted_passport_submissions"] == 0
    update_group.assert_not_awaited()
    stage_cleanup.assert_not_called()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"].endswith("idempotent_replay")
    session.execute.assert_not_awaited()
    session.commit.assert_awaited_once_with()
