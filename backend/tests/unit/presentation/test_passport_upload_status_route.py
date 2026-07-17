"""Regression tests for public passport extraction status polling."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks

from app.presentation.api.v1.routes.passports import get_upload_passport_status


class PassportUploadStatusRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshots_submission_before_redelivery_commit(self) -> None:
        group_id = uuid.uuid4()
        submission_id = uuid.uuid4()
        group = SimpleNamespace(id=group_id)
        submission = SimpleNamespace(id=submission_id, group_id=group_id)
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

        async def response(result, **_kwargs):  # type: ignore[no-untyped-def]
            self.assertIs(result, response_snapshot)
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
                session=AsyncMock(),
            )

        self.assertIs(result, expected_response)
        self.assertEqual(events, ["snapshot", "dispatch_commit", "response"])


if __name__ == "__main__":
    unittest.main()
