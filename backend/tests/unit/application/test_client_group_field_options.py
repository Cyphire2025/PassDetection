from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock

from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.domain.exceptions.exceptions import ValidationError


class ClientGroupFieldOptionsTests(unittest.IsolatedAsyncioTestCase):
    def _build_use_case(self, group: ClientGroup, submission: PassportSubmission):
        passport_repo = AsyncMock()
        passport_repo.get_by_id_for_update.return_value = submission
        passport_repo.exists_contact_in_group.return_value = False
        group_repo = AsyncMock()
        group_repo.get_by_token.return_value = group
        storage_repo = AsyncMock()
        return ClientSubmitPassportUseCase(passport_repo, group_repo, storage_repo), passport_repo

    @staticmethod
    def _group(**options: bool) -> ClientGroup:
        return ClientGroup.create(
            name="Configured Group",
            token="public-group-token",
            agency_id=uuid.uuid4(),
            created_by_user_id=uuid.uuid4(),
            departure_cities=["Delhi", "Mumbai"],
            **options,
        )

    @staticmethod
    def _submission(group: ClientGroup) -> PassportSubmission:
        submission = PassportSubmission.create(
            group_id=group.id,
            agency_id=group.agency_id,
            client_name="Test Passenger",
            client_email=None,
            image_s3_key=f"{group.agency_id}/{group.id}/passport.jpg",
        )
        submission.passport_back_s3_key = f"{group.agency_id}/{group.id}/passport-back.jpg"
        return submission

    async def test_enabled_fields_are_required_and_persisted_with_canonical_values(self) -> None:
        group = self._group(
            base_city_enabled=True,
            nearest_international_airport_enabled=True,
            ask_nearest_domestic_airport=True,
            staff_code_enabled=True,
            meal_preference_enabled=True,
        )
        submission = self._submission(group)
        use_case, passport_repo = self._build_use_case(group, submission)

        await use_case.execute(
            submission.id,
            group_token=group.token,
            confirmed_fields={"passport_number": " P1234567 "},
            client_email="person@example.com",
            client_phone="+91 98765 43210",
            departure_city="delhi",
            nearest_domestic_airport="  Indira   Gandhi Domestic Terminal ",
            base_city="  New   Delhi ",
            staff_code=" STF-42 ",
            meal_preference="non veg",
        )

        self.assertEqual(submission.departure_city, "Delhi")
        self.assertEqual(
            submission.nearest_domestic_airport,
            "Indira Gandhi Domestic Terminal",
        )
        self.assertEqual(submission.confirmed_fields["base_city"], "New Delhi")
        self.assertEqual(submission.confirmed_fields["staff_code"], "STF-42")
        self.assertEqual(submission.confirmed_fields["meal_preference"], "Non Veg")
        passport_repo.update.assert_awaited_once_with(submission)

    async def test_invalid_enabled_meal_preference_is_rejected(self) -> None:
        group = self._group(meal_preference_enabled=True)
        submission = self._submission(group)
        use_case, _ = self._build_use_case(group, submission)

        with self.assertRaises(ValidationError):
            await use_case.execute(
                submission.id,
                group_token=group.token,
                confirmed_fields={"passport_number": "P1234567"},
                client_email="person@example.com",
                client_phone="9876543210",
                meal_preference="Vegan",
            )

    async def test_each_enabled_field_rejects_a_missing_value(self) -> None:
        cases = (
            ("base_city", {"base_city_enabled": True}),
            ("staff_code", {"staff_code_enabled": True}),
            ("meal_preference", {"meal_preference_enabled": True}),
            ("departure_city", {"nearest_international_airport_enabled": True}),
            (
                "nearest_domestic_airport",
                {"ask_nearest_domestic_airport": True},
            ),
        )
        for expected_field, options in cases:
            with self.subTest(field=expected_field):
                group = self._group(**options)
                submission = self._submission(group)
                use_case, _ = self._build_use_case(group, submission)

                with self.assertRaises(ValidationError) as context:
                    await use_case.execute(
                        submission.id,
                        group_token=group.token,
                        confirmed_fields={"passport_number": "P1234567"},
                        client_email="person@example.com",
                        client_phone="9876543210",
                    )

                self.assertEqual(context.exception.field, expected_field)

    async def test_disabled_fields_ignore_hidden_payload_values(self) -> None:
        group = self._group()
        submission = self._submission(group)
        use_case, _ = self._build_use_case(group, submission)

        await use_case.execute(
            submission.id,
            group_token=group.token,
            confirmed_fields={
                "passport_number": "P1234567",
                "base_city": "Injected",
                "staff_code": "Injected",
                "meal_preference": "Veg",
                "nearest_domestic_airport": "Injected",
            },
            client_email="person@example.com",
            client_phone="9876543210",
            departure_city="Injected",
            nearest_domestic_airport="Injected",
            base_city="Injected",
            staff_code="Injected",
            meal_preference="Veg",
        )

        self.assertIsNone(submission.departure_city)
        self.assertIsNone(submission.nearest_domestic_airport)
        self.assertNotIn("base_city", submission.confirmed_fields)
        self.assertNotIn("staff_code", submission.confirmed_fields)
        self.assertNotIn("meal_preference", submission.confirmed_fields)

    async def test_final_submit_requires_front_and_back_but_selfie_only_when_configured(self) -> None:
        optional_group = self._group()
        optional_submission = self._submission(optional_group)
        optional_use_case, optional_repo = self._build_use_case(optional_group, optional_submission)
        await optional_use_case.execute(
            optional_submission.id,
            group_token=optional_group.token,
            confirmed_fields={"passport_number": "P1234567"},
            client_email="person@example.com",
            client_phone="9876543210",
        )
        optional_repo.update.assert_awaited_once()

        required_group = self._group(require_selfie=True)
        required_submission = self._submission(required_group)
        required_use_case, _ = self._build_use_case(required_group, required_submission)
        with self.assertRaises(ValidationError) as selfie_error:
            await required_use_case.execute(
                required_submission.id,
                group_token=required_group.token,
                confirmed_fields={"passport_number": "P1234567"},
                client_email="person@example.com",
                client_phone="9876543210",
            )
        self.assertEqual(selfie_error.exception.field, "passport_photo_file")

        required_submission.passport_photo_s3_key = f"{required_group.id}/selfie.jpg"
        required_submission.passport_back_s3_key = None
        with self.assertRaises(ValidationError) as back_error:
            await required_use_case.execute(
                required_submission.id,
                group_token=required_group.token,
                confirmed_fields={"passport_number": "P1234567"},
                client_email="person@example.com",
                client_phone="9876543210",
            )
        self.assertEqual(back_error.exception.field, "passport_back_file")

    async def test_initial_upload_enforces_back_and_configured_selfie_before_storage(self) -> None:
        group_repo = AsyncMock()
        passport_repo = AsyncMock()
        storage_repo = AsyncMock()
        passport_repo.save_idempotent.side_effect = lambda submission: (
            submission,
            True,
        )
        use_case = SubmitPassportUseCase(group_repo, passport_repo, storage_repo)

        group_repo.get_by_token.return_value = self._group()
        with self.assertRaises(ValidationError) as back_error:
            await use_case.execute(
                token="public-group-token",
                file_content=b"front",
                content_type="image/jpeg",
                filename="front.jpg",
                client_name="Test Passenger",
            )
        self.assertEqual(back_error.exception.field, "passport_back_file")
        storage_repo.upload_file.assert_not_awaited()

        group_repo.get_by_token.return_value = self._group(require_selfie=True)
        with self.assertRaises(ValidationError) as selfie_error:
            await use_case.execute(
                token="public-group-token",
                file_content=b"front",
                content_type="image/jpeg",
                filename="front.jpg",
                client_name="Test Passenger",
                passport_back=(b"back", "image/jpeg", "back.jpg"),
            )
        self.assertEqual(selfie_error.exception.field, "passport_photo_file")
        storage_repo.upload_file.assert_not_awaited()

        group_repo.get_by_token.return_value = self._group()
        result = await use_case.execute(
            token="public-group-token",
            file_content=b"front",
            content_type="image/jpeg",
            filename="front.jpg",
            client_name="Test Passenger",
            passport_back=(b"back", "image/jpeg", "back.jpg"),
        )
        self.assertIsNone(result.passport_photo_s3_key)
        self.assertIsNotNone(result.passport_back_s3_key)
        self.assertEqual(storage_repo.upload_file.await_count, 2)

    async def test_initial_upload_rejects_file_mode_when_group_requires_camera(self) -> None:
        group_repo = AsyncMock()
        passport_repo = AsyncMock()
        storage_repo = AsyncMock()
        use_case = SubmitPassportUseCase(group_repo, passport_repo, storage_repo)
        group_repo.get_by_token.return_value = self._group(
            allow_files_from_device=False,
        )

        with self.assertRaises(ValidationError) as context:
            await use_case.execute(
                token="public-group-token",
                file_content=b"front",
                content_type="image/jpeg",
                filename="front.jpg",
                client_name="Test Passenger",
                passport_back=(b"back", "image/jpeg", "back.jpg"),
                acquisition_mode="file",
            )

        self.assertEqual(context.exception.field, "acquisition_mode")
        storage_repo.upload_file.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
