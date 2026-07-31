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
        group = SimpleNamespace(
            id=group_id,
            status="active",
            deleted_at=None,
        )
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
                "app.presentation.api.v1.routes.passports.ClientGroupRepository",
                return_value=group_repository,
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "PassportSubmissionRepository",
                return_value=submission_repository,
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "PassportProcessingJobRepository",
                return_value=job_repository,
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "queued_job_needs_redelivery",
                return_value=True,
            ),
            patch(
                "app.presentation.api.v1.routes.passports.AuthorizationPolicy."
                "passport_group_accepts_mutations",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "passport_submission_output_from_entity",
                side_effect=snapshot,
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "_dispatch_processing_job",
                new=dispatch,
            ),
            patch(
                "app.presentation.api.v1.routes.passports._response_from_dto",
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

    async def test_archived_group_poll_does_not_redeliver_queued_work(self) -> None:
        group_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        upload_credential = "private-upload-credential-12345678"
        submission = SimpleNamespace(
            id=submission_id,
            group_id=group_id,
            upload_idempotency_key=upload_credential,
        )
        response_snapshot = SimpleNamespace(id=submission_id)
        dispatch = AsyncMock()
        response = AsyncMock(return_value=object())

        with (
            patch(
                "app.presentation.api.v1.routes.passports.ClientGroupRepository",
                return_value=SimpleNamespace(
                    get_by_token=AsyncMock(
                        return_value=SimpleNamespace(
                            id=group_id,
                            status="archived",
                            deleted_at=None,
                        )
                    )
                ),
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "PassportSubmissionRepository",
                return_value=SimpleNamespace(
                    get_by_id=AsyncMock(return_value=submission)
                ),
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "PassportProcessingJobRepository",
                return_value=SimpleNamespace(
                    latest_for_submission=AsyncMock(
                        return_value=SimpleNamespace(id=uuid.uuid4())
                    )
                ),
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "queued_job_needs_redelivery",
                return_value=True,
            ),
            patch(
                "app.presentation.api.v1.routes.passports.AuthorizationPolicy."
                "passport_group_accepts_mutations",
                AsyncMock(return_value=False),
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "passport_submission_output_from_entity",
                return_value=response_snapshot,
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "_dispatch_processing_job",
                dispatch,
            ),
            patch(
                "app.presentation.api.v1.routes.passports._response_from_dto",
                response,
            ),
        ):
            await get_upload_passport_status(
                token="public-upload-token",
                submission_id=submission_id,
                background_tasks=BackgroundTasks(),
                upload_session_id=upload_credential,
                session=AsyncMock(),
            )

        dispatch.assert_not_awaited()
        response.assert_awaited_once()

    async def test_cross_submission_credential_is_rejected_before_response(
        self,
    ) -> None:
        group_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        group_repository = SimpleNamespace(
            get_by_token=AsyncMock(return_value=SimpleNamespace(id=group_id))
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
                "app.presentation.api.v1.routes.passports.ClientGroupRepository",
                return_value=group_repository,
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "PassportSubmissionRepository",
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
        submission_id = uuid.uuid4()
        group_repository = SimpleNamespace(
            get_by_token=AsyncMock(return_value=SimpleNamespace(id=group_id))
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

        with (
            patch(
                "app.presentation.api.v1.routes.passports.ClientGroupRepository",
                return_value=group_repository,
            ),
            patch(
                "app.presentation.api.v1.routes.passports."
                "PassportSubmissionRepository",
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


if __name__ == "__main__":
    unittest.main()
