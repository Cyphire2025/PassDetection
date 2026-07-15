from __future__ import annotations

import unittest

from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.exceptions.exceptions import ValidationError


class SubmitPassportUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_passport_upload_requires_visa_selfie_before_any_storage_work(self) -> None:
        use_case = SubmitPassportUseCase(
            client_group_repo=None,  # type: ignore[arg-type]
            passport_repo=None,  # type: ignore[arg-type]
            storage_repo=None,  # type: ignore[arg-type]
        )

        with self.assertRaises(ValidationError) as error:
            await use_case.execute(
                token="public-token",
                file_content=b"passport-front",
                content_type="image/jpeg",
                filename="front.jpg",
                client_name="Test Passenger",
                passport_photo=None,
            )

        self.assertEqual(error.exception.field, "passport_photo_file")
        self.assertIn("VISA selfie", error.exception.message)
