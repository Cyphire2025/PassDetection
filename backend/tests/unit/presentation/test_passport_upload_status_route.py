"""Regression tests for public passport extraction status polling."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, HTTPException

from app.presentation.api.v1.routes.passports import (
    discard_public_upload,
    get_upload_passport_status,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse,
)


class PassportUploadStatusRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_public_response_schema_never_exposes_upload_credential(self) -> None:
        self.assertNotIn(
            "upload_idempotency_key",
            PassportSubmissionResponse.model_fields,
        )

    async def test_snapshots_submission_before_redelivery_commit(self) -> None:
        group_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        group = SimpleNamespace(id=group_id, is_active=lambda: True, deleted_at=None)
        upload_credential = "private-upload-credential-12345678"
        submission = SimpleNamespace(
            id=submission_id,
            group_id=group_id,
            upload_idempotency_key=upload_credential,
        )
        job = SimpleNamespace(id=uuid.uuid4())
        response_snapshot = SimpleNamespace(id=submission_id)
        expected_response = object()
        events: list[str] = []

        group_repository = SimpleNamespace(
            get_by_token=AsyncMock(return_value=group)
        )
        submission_repository = SimpleNamespace(
            get_by_id=AsyncMock(return_value=submission)
        )
        job_repository = SimpleNamespace(
            latest_for_submission=AsyncMock(return_value=job)
        )

        def snapshot(entity, *, job):  # type: ignore[no-untyped-def]
            self.assertIs(entity, submission)
            events.append("snapshot")
            return response_snapshot

        async def dispatch(result, **_kwargs):  # type: ignore[no-untyped-def]
            self.assertIs(result, response_snapshot)
            events.append("dispatch_commit")

        async def response(  # type: ignore[no-untyped-def]
            result,
            *,
            include_document_urls,
            **_kwargs,
        ):
            self.assertIs(result, response_snapshot)
            self.assertFalse(include_document_urls)
            events.append("response")
            return expected_response

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.ClientGroupRepository',
                return_value=group_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.PassportSubmissionRepository',
                return_value=submission_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.PassportProcessingJobRepository',
                return_value=job_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.queued_job_needs_redelivery',
                return_value=True,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.passport_submission_output_from_entity',
                side_effect=snapshot,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload._dispatch_processing_job',
                new=dispatch,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload._response_from_dto',
                new=response,
            ),
        ):
            result = await get_upload_passport_status(
                token="public-upload-token",
                submission_id=submission_id,
                background_tasks=BackgroundTasks(),
                upload_session_id=upload_credential,
                session=AsyncMock(),
            )

        self.assertIs(result, expected_response)
        self.assertEqual(events, ["snapshot", "dispatch_commit", "response"])

    async def test_cross_submission_credential_is_rejected_before_response(
        self,
    ) -> None:
        group_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        group_repository = SimpleNamespace(
            get_by_token=AsyncMock(return_value=SimpleNamespace(id=group_id, is_active=lambda: True, deleted_at=None))
        )
        submission_repository = SimpleNamespace(
            get_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id=submission_id,
                    group_id=group_id,
                    upload_idempotency_key=(
                        "target-private-upload-credential-1234"
                    ),
                )
            )
        )

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.ClientGroupRepository',
                return_value=group_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.PassportSubmissionRepository',
                return_value=submission_repository,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await get_upload_passport_status(
                    token="public-upload-token",
                    submission_id=submission_id,
                    background_tasks=BackgroundTasks(),
                    upload_session_id=(
                        "another-private-upload-credential-5678"
                    ),
                    session=AsyncMock(),
                )

        self.assertEqual(raised.exception.status_code, 404)

    async def test_cross_submission_credential_cannot_discard_draft(
        self,
    ) -> None:
        group_id = uuid.uuid4()
        agency_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        group = SimpleNamespace(id=group_id, agency_id=agency_id, is_active=lambda: True, deleted_at=None)
        group_repository = SimpleNamespace(
            get_by_token=AsyncMock(return_value=group)
        )
        submission_repository = SimpleNamespace(
            get_by_id_for_update=AsyncMock(
                return_value=SimpleNamespace(
                    id=submission_id,
                    group_id=group_id,
                    status=SimpleNamespace(value="ready_for_client_review"),
                    upload_idempotency_key=(
                        "target-private-upload-credential-1234"
                    ),
                )
            ),
            delete=AsyncMock(),
        )
        session = AsyncMock()
        session.scalar.return_value = SimpleNamespace(
            id=group_id,
            agency_id=agency_id,
            passport_legal_hold=False,
        )

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.ClientGroupRepository',
                return_value=group_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.PassportSubmissionRepository',
                return_value=submission_repository,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await discard_public_upload(
                    token="public-upload-token",
                    submission_id=submission_id,
                    upload_session_id=(
                        "another-private-upload-credential-5678"
                    ),
                    session=session,
                )

        self.assertEqual(raised.exception.status_code, 404)
        submission_repository.delete.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_public_draft_discard_commits_cleanup_tombstone_before_worker(self) -> None:
        group_id = uuid.uuid4()
        agency_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        credential = "private-upload-credential-1234567890"
        group = SimpleNamespace(id=group_id, agency_id=agency_id, is_active=lambda: True, deleted_at=None)
        locked_group = SimpleNamespace(
            id=group_id,
            agency_id=agency_id,
            passport_legal_hold=False,
        )
        submission = SimpleNamespace(
            id=submission_id,
            group_id=group_id,
            status=SimpleNamespace(value="processing"),
            upload_idempotency_key=credential,
            image_s3_key="front/example.jpg",
            thumbnail_s3_key=None,
            passport_photo_s3_key=None,
            passport_back_s3_key="back/example.jpg",
            passport_cover_s3_key="cover/example.jpg",
            passport_back_cover_s3_key="back-cover/example.jpg",
        )
        events: list[str] = []
        submission_repository = SimpleNamespace(
            get_by_id_for_update=AsyncMock(return_value=submission),
            delete=AsyncMock(side_effect=lambda _identifier: events.append("row-delete")),
        )
        session = AsyncMock()
        session.scalar.return_value = locked_group
        session.commit.side_effect = lambda: events.append("commit")
        audit = AsyncMock(side_effect=lambda **_kwargs: events.append("audit"))
        cleanup_job = SimpleNamespace(
            id=uuid.uuid4(),
            object_count=4,
        )

        def stage(*_args, **_kwargs):
            self.assertEqual(
                set(_kwargs["storage_keys"]),
                {"front/example.jpg", "back/example.jpg", "cover/example.jpg", "back-cover/example.jpg"},
            )
            events.append("cleanup-tombstone")
            return (cleanup_job,)

        async def process(_job_id):
            events.append("object-worker")

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.ClientGroupRepository',
                return_value=SimpleNamespace(get_by_token=AsyncMock(return_value=group)),
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.PassportSubmissionRepository',
                return_value=submission_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.stage_storage_cleanup_jobs',
                side_effect=stage,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.AuditLogRepository',
                return_value=SimpleNamespace(record=audit),
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.process_storage_cleanup_job',
                new=process,
            ),
        ):
            response = await discard_public_upload(
                token="public-upload-token",
                submission_id=submission_id,
                upload_session_id=credential,
                session=session,
            )

        self.assertEqual(response, {"discarded": True})
        self.assertEqual(
            events,
            ["cleanup-tombstone", "row-delete", "audit", "commit", "object-worker"],
        )

    async def test_public_draft_discard_is_blocked_by_locked_legal_hold(self) -> None:
        group_id = uuid.uuid4()
        agency_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        credential = "private-upload-credential-1234567890"
        group = SimpleNamespace(id=group_id, agency_id=agency_id, is_active=lambda: True, deleted_at=None)
        submission_repository = SimpleNamespace(
            get_by_id_for_update=AsyncMock(
                return_value=SimpleNamespace(
                    id=submission_id,
                    group_id=group_id,
                    status=SimpleNamespace(value="processing"),
                    upload_idempotency_key=credential,
                )
            ),
            delete=AsyncMock(),
        )
        session = AsyncMock()
        session.scalar.return_value = SimpleNamespace(
            id=group_id,
            agency_id=agency_id,
            passport_legal_hold=True,
        )
        audit = AsyncMock()

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.ClientGroupRepository',
                return_value=SimpleNamespace(get_by_token=AsyncMock(return_value=group)),
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.PassportSubmissionRepository',
                return_value=submission_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.AuditLogRepository',
                return_value=SimpleNamespace(record=audit),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await discard_public_upload(
                    token="public-upload-token",
                    submission_id=submission_id,
                    upload_session_id=credential,
                    session=session,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail["code"],
            "PASSPORT_LEGAL_HOLD_ACTIVE",
        )
        self.assertEqual(audit.await_args.kwargs["result"], "blocked")
        submission_repository.delete.assert_not_awaited()
        session.commit.assert_awaited_once()

    async def test_public_draft_commit_failure_never_invokes_object_worker(self) -> None:
        group_id = uuid.uuid4()
        agency_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        credential = "private-upload-credential-1234567890"
        group = SimpleNamespace(id=group_id, agency_id=agency_id, is_active=lambda: True, deleted_at=None)
        submission = SimpleNamespace(
            id=submission_id,
            group_id=group_id,
            status=SimpleNamespace(value="processing"),
            upload_idempotency_key=credential,
            image_s3_key="front/example.jpg",
            thumbnail_s3_key=None,
            passport_photo_s3_key=None,
            passport_back_s3_key=None,
            passport_cover_s3_key=None,
            passport_back_cover_s3_key=None,
        )
        session = AsyncMock()
        session.scalar.return_value = SimpleNamespace(
            id=group_id,
            agency_id=agency_id,
            passport_legal_hold=False,
        )
        session.commit.side_effect = RuntimeError("commit failed")
        process = AsyncMock()

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.ClientGroupRepository',
                return_value=SimpleNamespace(get_by_token=AsyncMock(return_value=group)),
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.PassportSubmissionRepository',
                return_value=SimpleNamespace(
                    get_by_id_for_update=AsyncMock(return_value=submission),
                    delete=AsyncMock(),
                ),
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.stage_storage_cleanup_jobs',
                return_value=(SimpleNamespace(id=uuid.uuid4(), object_count=1),),
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.AuditLogRepository',
                return_value=SimpleNamespace(record=AsyncMock()),
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.public_upload.process_storage_cleanup_job',
                new=process,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                await discard_public_upload(
                    token="public-upload-token",
                    submission_id=submission_id,
                    upload_session_id=credential,
                    session=session,
                )

        process.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
