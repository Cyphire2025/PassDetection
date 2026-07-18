from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from app.application.use_cases.client_groups.create_qualifier_selection_use_case import (
    CreateQualifierSelectionUseCase,
)
from app.application.use_cases.client_groups.get_qualifier_selection_use_case import (
    GetQualifierSelectionUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import (
    SubmitPassportUseCase,
)
from app.domain.entities.entities import (
    ClientGroup,
    PassportSubmission,
    QualifierSelection,
)
from app.domain.exceptions.exceptions import GroupClosedError, ValidationError
from app.domain.value_objects.qualifier_relations import (
    hash_qualifier_selection_token,
)


class QualifierSelectionUseCaseTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _group(*, enabled: bool = True) -> ClientGroup:
        return ClientGroup.create(
            name="Qualifier Group",
            token="public-qualifier-group-token",
            agency_id=uuid.uuid4(),
            created_by_user_id=uuid.uuid4(),
            relation_with_qualifier_enabled=enabled,
        )

    async def test_create_persists_self_without_storing_the_bearer_token(self) -> None:
        group = self._group()
        group_repo = AsyncMock()
        group_repo.get_by_token.return_value = group
        selection_repo = AsyncMock()
        use_case = CreateQualifierSelectionUseCase(group_repo, selection_repo)

        result = await use_case.execute(
            group_token=group.token,
            is_self=True,
            relation_code=None,
        )

        saved = selection_repo.save.await_args.args[0]
        self.assertTrue(result.is_self)
        self.assertEqual(result.relation_label, "Self")
        self.assertIsNotNone(result.selection_token)
        self.assertEqual(
            saved.token_hash,
            hash_qualifier_selection_token(result.selection_token or ""),
        )
        self.assertNotEqual(saved.token_hash, result.selection_token)

    async def test_disabled_group_and_friend_are_rejected(self) -> None:
        group_repo = AsyncMock()
        selection_repo = AsyncMock()
        group_repo.get_by_token.return_value = self._group(enabled=False)
        use_case = CreateQualifierSelectionUseCase(group_repo, selection_repo)

        with self.assertRaises(ValidationError):
            await use_case.execute(
                group_token="public-qualifier-group-token",
                is_self=True,
                relation_code=None,
            )
        selection_repo.save.assert_not_awaited()

        group_repo.get_by_token.return_value = self._group()
        with self.assertRaises(ValidationError):
            await use_case.execute(
                group_token="public-qualifier-group-token",
                is_self=False,
                relation_code="friend",
            )

    async def test_get_reports_active_expired_and_consumed_for_resume(self) -> None:
        group = self._group()
        group_repo = AsyncMock()
        group_repo.get_by_token.return_value = group
        selection_repo = AsyncMock()
        now = datetime.now(tz=UTC)
        active = QualifierSelection.create(
            group_id=group.id,
            token_hash=hash_qualifier_selection_token("a" * 43),
            is_self=False,
            relation_code="spouse",
            selected_at=now,
            expires_at=now + timedelta(hours=1),
        )
        selection_repo.get_by_token_hash.return_value = active
        selection_repo.get_submission_id.return_value = None
        use_case = GetQualifierSelectionUseCase(group_repo, selection_repo)

        result = await use_case.execute(
            group_token=group.token,
            selection_token="a" * 43,
        )
        self.assertEqual(result.status, "active")
        self.assertEqual(result.relation_code, "spouse")

        active.expires_at = now - timedelta(seconds=1)
        expired = await use_case.execute(
            group_token=group.token,
            selection_token="a" * 43,
        )
        self.assertEqual(expired.status, "expired")

        submission_id = uuid.uuid4()
        selection_repo.get_submission_id.return_value = submission_id
        consumed = await use_case.execute(
            group_token=group.token,
            selection_token="a" * 43,
        )
        self.assertEqual(consumed.status, "consumed")
        self.assertEqual(consumed.submission_id, submission_id)

    async def test_get_does_not_resume_selection_for_inactive_link(self) -> None:
        group = self._group()
        group.archive()
        group_repo = AsyncMock()
        group_repo.get_by_token.return_value = group
        selection_repo = AsyncMock()

        with self.assertRaises(GroupClosedError):
            await GetQualifierSelectionUseCase(
                group_repo,
                selection_repo,
            ).execute(
                group_token=group.token,
                selection_token="a" * 43,
            )

        selection_repo.get_by_token_hash.assert_not_awaited()


class QualifierUploadEnforcementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.group = ClientGroup.create(
            name="Qualifier Group",
            token="public-qualifier-group-token",
            agency_id=uuid.uuid4(),
            created_by_user_id=uuid.uuid4(),
            relation_with_qualifier_enabled=True,
        )
        self.raw_selection_token = "s" * 43
        now = datetime.now(tz=UTC)
        self.selection = QualifierSelection.create(
            group_id=self.group.id,
            token_hash=hash_qualifier_selection_token(
                self.raw_selection_token
            ),
            is_self=False,
            relation_code="spouse",
            selected_at=now,
            expires_at=now + timedelta(hours=1),
        )
        self.group_repo = AsyncMock()
        self.group_repo.get_by_token.return_value = self.group
        self.passport_repo = AsyncMock()
        self.passport_repo.get_by_upload_idempotency_key.return_value = None
        self.storage_repo = AsyncMock()
        self.storage_repo.upload_file.side_effect = (
            lambda *, file_content, file_name, content_type: file_name
        )
        self.selection_repo = AsyncMock()
        self.selection_repo.get_by_token_hash.return_value = self.selection
        self.selection_repo.get_submission_id.return_value = None

        async def save_idempotent(submission):
            return submission, True

        self.passport_repo.save_idempotent.side_effect = save_idempotent

    def _use_case(self) -> SubmitPassportUseCase:
        return SubmitPassportUseCase(
            self.group_repo,
            self.passport_repo,
            self.storage_repo,
            qualifier_selection_repo=self.selection_repo,
        )

    async def _upload(self, **overrides):
        request = {
            "token": self.group.token,
            "file_content": b"front",
            "content_type": "image/jpeg",
            "filename": "front.jpg",
            "client_name": "Traveller",
            "passport_back": (b"back", "image/jpeg", "back.jpg"),
            "upload_idempotency_key": (
                "qualifier-upload-key-1234567890abcdef"
            ),
            "qualifier_selection_token": self.raw_selection_token,
        }
        request.update(overrides)
        return await self._use_case().execute(**request)

    async def test_enabled_upload_requires_a_server_selection_before_storage(self) -> None:
        with self.assertRaises(ValidationError) as context:
            await self._upload(qualifier_selection_token=None)

        self.assertEqual(
            context.exception.field,
            "qualifier_selection_token",
        )
        self.storage_repo.upload_file.assert_not_awaited()

    async def test_valid_selection_is_snapshotted_on_single_submission(self) -> None:
        result = await self._upload()

        self.assertTrue(result.qualifier_enabled_snapshot)
        self.assertFalse(result.qualifier_is_self)
        self.assertEqual(result.qualifier_relation_code, "spouse")
        self.assertEqual(result.qualifier_relation_label, "Spouse")
        saved = self.passport_repo.save_idempotent.await_args.args[0]
        self.assertEqual(saved.qualifier_selection_id, self.selection.id)
        self.assertEqual(saved.submission_mode, "single")

    async def test_self_selection_is_snapshotted_without_a_relation_code(self) -> None:
        now = datetime.now(tz=UTC)
        self.selection = QualifierSelection.create(
            group_id=self.group.id,
            token_hash=hash_qualifier_selection_token(
                self.raw_selection_token
            ),
            is_self=True,
            relation_code=None,
            selected_at=now,
            expires_at=now + timedelta(hours=1),
        )
        self.selection_repo.get_by_token_hash.return_value = self.selection

        result = await self._upload()

        self.assertTrue(result.qualifier_is_self)
        self.assertIsNone(result.qualifier_relation_code)
        self.assertEqual(result.qualifier_relation_label, "Self")

    async def test_expired_or_wrong_group_selection_is_rejected_before_storage(
        self,
    ) -> None:
        self.selection.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        with self.assertRaises(ValidationError):
            await self._upload()
        self.storage_repo.upload_file.assert_not_awaited()

        self.selection.expires_at = datetime.now(tz=UTC) + timedelta(hours=1)
        self.selection.group_id = uuid.uuid4()
        with self.assertRaises(ValidationError):
            await self._upload()
        self.storage_repo.upload_file.assert_not_awaited()

    async def test_used_selection_only_allows_same_idempotent_replay(self) -> None:
        existing = PassportSubmission.create(
            group_id=self.group.id,
            agency_id=self.group.agency_id,
            client_name="Traveller",
            client_email=None,
            image_s3_key="drafts/existing.jpg",
            upload_idempotency_key=(
                "qualifier-upload-key-1234567890abcdef"
            ),
        )
        existing.attach_qualifier_selection(self.selection)
        self.selection_repo.get_submission_id.return_value = existing.id
        self.passport_repo.get_by_id.return_value = existing
        self.passport_repo.get_by_upload_idempotency_key.return_value = existing

        replay = await self._upload()
        self.assertEqual(replay.id, existing.id)
        self.storage_repo.upload_file.assert_not_awaited()

        with self.assertRaises(ValidationError):
            await self._upload(
                upload_idempotency_key=(
                    "different-upload-key-1234567890abcdef"
                ),
            )

    async def test_disabled_legacy_group_preserves_old_upload_flow(self) -> None:
        self.group.relation_with_qualifier_enabled = False

        result = await self._upload(qualifier_selection_token=None)

        self.assertFalse(result.qualifier_enabled_snapshot)
        self.assertIsNone(result.qualifier_relation_code)
        self.selection_repo.get_by_token_hash.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
