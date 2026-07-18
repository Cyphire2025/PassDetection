from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock

from app.application.use_cases.passports.reconcile_passport_upload_use_case import (
    ReconcilePassportUploadUseCase,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission


class ReconcilePassportUploadUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.group = ClientGroup.create(
            name="Recovery Group",
            token="active-upload-link-token",
            agency_id=uuid.uuid4(),
            created_by_user_id=uuid.uuid4(),
        )
        self.attempt_key = "upload-attempt-12345678-abcdef-123456"
        self.submission = PassportSubmission.create(
            group_id=self.group.id,
            agency_id=self.group.agency_id,
            client_name="Persisted Traveller",
            client_email=None,
            image_s3_key="drafts/front.jpg",
            upload_idempotency_key=self.attempt_key,
        )
        self.group_repo = AsyncMock()
        self.group_repo.get_by_token.return_value = self.group
        self.passport_repo = AsyncMock()
        self.use_case = ReconcilePassportUploadUseCase(
            client_group_repo=self.group_repo,
            passport_repo=self.passport_repo,
        )

    async def test_lost_upload_response_recovers_committed_submission(self) -> None:
        self.passport_repo.get_by_upload_idempotency_key.return_value = (
            self.submission
        )

        submission_id = await self.use_case.execute(
            token=self.group.token,
            upload_idempotency_key=self.attempt_key,
        )

        self.assertEqual(submission_id, self.submission.id)
        self.passport_repo.get_by_upload_idempotency_key.assert_awaited_once_with(
            self.group.id,
            self.attempt_key,
        )

    async def test_unknown_key_and_wrong_link_have_the_same_empty_result(self) -> None:
        self.passport_repo.get_by_upload_idempotency_key.return_value = None
        unknown = await self.use_case.execute(
            token=self.group.token,
            upload_idempotency_key="unknown-attempt-12345678-abcdef-123456",
        )

        other_group = ClientGroup.create(
            name="Other Group",
            token="other-upload-link-token",
            agency_id=uuid.uuid4(),
            created_by_user_id=uuid.uuid4(),
        )
        self.group_repo.get_by_token.return_value = other_group
        wrong_link = await self.use_case.execute(
            token=other_group.token,
            upload_idempotency_key=self.attempt_key,
        )

        self.assertIsNone(unknown)
        self.assertIsNone(wrong_link)
        self.passport_repo.get_by_upload_idempotency_key.assert_any_await(
            self.group.id,
            "unknown-attempt-12345678-abcdef-123456",
        )
        self.passport_repo.get_by_upload_idempotency_key.assert_any_await(
            other_group.id,
            self.attempt_key,
        )

    async def test_missing_or_closed_link_does_not_probe_submission_keys(self) -> None:
        self.group_repo.get_by_token.return_value = None
        missing = await self.use_case.execute(
            token="missing-upload-link-token",
            upload_idempotency_key=self.attempt_key,
        )

        self.group.close()
        self.group_repo.get_by_token.return_value = self.group
        expired = await self.use_case.execute(
            token=self.group.token,
            upload_idempotency_key=self.attempt_key,
        )

        self.assertIsNone(missing)
        self.assertIsNone(expired)
        self.passport_repo.get_by_upload_idempotency_key.assert_not_awaited()

    async def test_malformed_key_is_rejected_before_link_or_repository_lookup(
        self,
    ) -> None:
        result = await self.use_case.execute(
            token=self.group.token,
            upload_idempotency_key="bad key",
        )

        self.assertIsNone(result)
        self.group_repo.get_by_token.assert_not_awaited()
        self.passport_repo.get_by_upload_idempotency_key.assert_not_awaited()

    async def test_reconciliation_retries_are_read_only_and_stable(self) -> None:
        self.passport_repo.get_by_upload_idempotency_key.return_value = (
            self.submission
        )

        first = await self.use_case.execute(
            token=self.group.token,
            upload_idempotency_key=self.attempt_key,
        )
        second = await self.use_case.execute(
            token=self.group.token,
            upload_idempotency_key=self.attempt_key,
        )

        self.assertEqual(first, self.submission.id)
        self.assertEqual(second, self.submission.id)
        self.assertEqual(
            self.passport_repo.get_by_upload_idempotency_key.await_count,
            2,
        )
        self.passport_repo.save.assert_not_awaited()
        self.passport_repo.save_idempotent.assert_not_awaited()
        self.passport_repo.update.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
