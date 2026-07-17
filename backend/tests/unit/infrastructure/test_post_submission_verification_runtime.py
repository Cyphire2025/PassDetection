"""Durable retry behavior for post-submit provider failures."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.application.interfaces.post_submission_verification import (
    PostSubmissionVerificationResult,
)
from app.infrastructure.verification.runtime import _handle_job_failure


class PostSubmissionVerificationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_is_queued_without_persisting_review(
        self,
    ) -> None:
        session = AsyncMock()
        repository = SimpleNamespace(
            mark_retryable=AsyncMock(),
            get=AsyncMock(return_value=SimpleNamespace(status="queued")),
        )
        with (
            patch(
                "app.infrastructure.verification.runtime."
                "PostSubmissionVerificationJobRepository",
                return_value=repository,
            ),
            patch(
                "app.infrastructure.verification.runtime."
                "_persist_terminal_needs_review",
                new_callable=AsyncMock,
            ) as persist_terminal,
        ):
            should_retry = await _handle_job_failure(
                session=session,
                job_id=uuid.uuid4(),
                submission_id=uuid.uuid4(),
                verification_revision=1,
                error_code="provider_unavailable",
            )

        self.assertTrue(should_retry)
        session.commit.assert_awaited_once()
        persist_terminal.assert_not_awaited()

    async def test_attempt_exhaustion_persists_original_provider_fallback(
        self,
    ) -> None:
        session = AsyncMock()
        repository = SimpleNamespace(
            mark_retryable=AsyncMock(),
            get=AsyncMock(return_value=SimpleNamespace(status="failed")),
        )
        terminal = PostSubmissionVerificationResult.fallback(
            provider_status="provider_unavailable",
            reason_code="provider_unavailable",
            model="gemini-3.1-flash-lite",
        )
        with (
            patch(
                "app.infrastructure.verification.runtime."
                "PostSubmissionVerificationJobRepository",
                return_value=repository,
            ),
            patch(
                "app.infrastructure.verification.runtime."
                "_persist_terminal_needs_review",
                new_callable=AsyncMock,
            ) as persist_terminal,
        ):
            should_retry = await _handle_job_failure(
                session=session,
                job_id=uuid.uuid4(),
                submission_id=uuid.uuid4(),
                verification_revision=1,
                error_code="provider_unavailable",
                terminal_verification=terminal,
            )

        self.assertFalse(should_retry)
        persist_terminal.assert_awaited_once()
        self.assertIs(
            persist_terminal.await_args.kwargs["verification"],
            terminal,
        )
