"""Route-level guards for staff-triggered post-submission AI retry."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks

from app.presentation.api.v1.routes.passports import (
    retry_post_submission_verification,
)


class RetryPostSubmissionVerificationRouteTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_authorizes_and_commits_durable_job_before_dispatch(self) -> None:
        submission_id = uuid.uuid4()
        user_id = uuid.uuid4()
        agency_id = uuid.uuid4()
        group_id = uuid.uuid4()
        events: list[str] = []

        current_user = SimpleNamespace(id=user_id)
        existing = SimpleNamespace(id=submission_id)
        result = SimpleNamespace(
            id=submission_id,
            agency_id=agency_id,
            group_id=group_id,
            post_submission_verification_revision=2,
        )
        retry_result = SimpleNamespace(
            submission=result,
            previous_provider_status="provider_unavailable",
            previous_reason_code="provider_unavailable",
        )
        verification_job = SimpleNamespace(
            id=uuid.uuid4(),
            status="queued",
        )

        get_use_case = SimpleNamespace(execute=AsyncMock(return_value=existing))
        retry_use_case = SimpleNamespace(execute=AsyncMock(return_value=retry_result))
        authorization = SimpleNamespace(
            require_confirm_passport=AsyncMock(
                side_effect=lambda *_args: events.append("authorize")
            )
        )
        job_repository = SimpleNamespace(
            enqueue=AsyncMock(
                side_effect=lambda **_kwargs: (
                    events.append("enqueue"),
                    verification_job,
                )[1]
            ),
            set_task_id=AsyncMock(),
        )
        audit_repository = SimpleNamespace(
            record=AsyncMock(side_effect=lambda **_kwargs: events.append("audit"))
        )
        dispatcher = SimpleNamespace(
            dispatch_async=AsyncMock(side_effect=lambda **_kwargs: events.append("dispatch"))
        )
        session = AsyncMock()
        session.commit.side_effect = lambda: events.append("commit")
        expected_response = object()

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review.AuthorizationPolicy',
                return_value=authorization,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review.PostSubmissionVerificationJobRepository',
                return_value=job_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review.AuditLogRepository',
                return_value=audit_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review.PostSubmissionVerificationDispatcher',
                return_value=dispatcher,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review._response_from_dto',
                new=AsyncMock(return_value=expected_response),
            ),
        ):
            response = await retry_post_submission_verification(
                submission_id=submission_id,
                background_tasks=BackgroundTasks(),
                _csrf=None,
                current_user=current_user,
                get_use_case=get_use_case,
                retry_use_case=retry_use_case,
                session=session,
            )

        self.assertIs(response, expected_response)
        self.assertEqual(
            events,
            ["authorize", "enqueue", "audit", "commit", "dispatch"],
        )
        authorization.require_confirm_passport.assert_awaited_once_with(
            current_user,
            existing,
        )
        job_repository.enqueue.assert_awaited_once_with(
            submission_id=submission_id,
            verification_revision=2,
        )
        audit_metadata = audit_repository.record.await_args.kwargs["metadata"]
        self.assertEqual(
            audit_metadata["previous_provider_status"],
            "provider_unavailable",
        )
        self.assertNotIn("confirmed_fields", audit_metadata)
