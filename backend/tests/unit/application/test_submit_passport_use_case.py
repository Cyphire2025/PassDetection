from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.exceptions.exceptions import EntityNotFoundError


class SubmitPassportUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_passport_upload_allows_missing_visa_selfie(self) -> None:
        client_group_repo = AsyncMock()
        client_group_repo.get_by_token.return_value = None
        use_case = SubmitPassportUseCase(
            client_group_repo=client_group_repo,
            passport_repo=None,  # type: ignore[arg-type]
            storage_repo=None,  # type: ignore[arg-type]
        )

        with self.assertRaises(EntityNotFoundError):
            await use_case.execute(
                token="public-token",
                file_content=b"passport-front",
                content_type="image/jpeg",
                filename="front.jpg",
                client_name="Test Passenger",
                passport_photo=None,
            )

        client_group_repo.get_by_token.assert_awaited_once_with(
            "public-token",
            for_update=True,
        )
