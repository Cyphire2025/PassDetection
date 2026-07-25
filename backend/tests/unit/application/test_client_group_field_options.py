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
    def _group(**options: object) -> ClientGroup:
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
        submission.extracted_fields = {
            "ai_verification": {
                "status": "verified",
                "available": True,
            }
        }
        return submission

    async def test_final_submit_rejects_wrong_document_even_with_manual_fields(
        self,
    ) -> None:
        group = self._group()
        submission = self._submission(group)
        submission.extracted_fields = {
            "ai_verification": {
                "status": "wrong_document",
                "available": False,
                "document_class": "aadhaar",
            }
        }
        use_case, passport_repo = self._build_use_case(group, submission)

        with self.assertRaises(ValidationError) as context:
            await use_case.execute(
                submission.id,
                group_token=group.token,
                confirmed_fields={
                    "surname": "KUMAR",
                    "given_names": "NIPUN",
                    "passport_number": "P1234567",
                },
                client_email="person@example.com",
                client_phone="9876543210",
            )

        self.assertEqual(context.exception.field, "file")
        self.assertIn("passport photo and details page", str(context.exception))
        passport_repo.update.assert_not_awaited()

    async def test_final_submit_fails_closed_until_classification_is_available(
        self,
    ) -> None:
        group = self._group()
        submission = self._submission(group)
        submission.extracted_fields = {
            "ai_verification": {
                "status": "provider_unavailable",
                "available": False,
            }
        }
        use_case, passport_repo = self._build_use_case(group, submission)

        with self.assertRaises(ValidationError) as context:
            await use_case.execute(
                submission.id,
                group_token=group.token,
                confirmed_fields={"passport_number": "P1234567"},
                client_email="person@example.com",
                client_phone="9876543210",
            )

        self.assertEqual(context.exception.field, "file")
        passport_repo.update.assert_not_awaited()

    async def test_enabled_fields_are_required_and_persisted_with_canonical_values(self) -> None:
        group = self._group(
            base_city_enabled=True,
            nearest_international_airport_enabled=True,
            ask_nearest_domestic_airport=True,
            staff_code_enabled=True,
            agent_employee_code_enabled=True,
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
            agent_employee_type="Agent",
            agent_employee_code="0012345678",
            meal_preference="non veg",
        )

        self.assertEqual(submission.departure_city, "Delhi")
        self.assertEqual(
            submission.nearest_domestic_airport,
            "Indira Gandhi Domestic Terminal",
        )
        self.assertEqual(submission.confirmed_fields["base_city"], "New Delhi")
        self.assertEqual(submission.confirmed_fields["staff_code"], "STF-42")
        self.assertEqual(submission.confirmed_fields["agent_employee_type"], "agent")
        self.assertEqual(submission.confirmed_fields["agent_employee_code"], "0012345678")
        self.assertEqual(submission.confirmed_fields["meal_preference"], "Non Veg")
        passport_repo.update.assert_awaited_once_with(submission)

    async def test_typed_group_fields_and_custom_details_are_required_and_saved(
        self,
    ) -> None:
        detail_id = uuid.uuid4()
        group = self._group(
            designation_enabled=True,
            agency_dealership_name_enabled=True,
            custom_details=[
                {
                    "id": str(detail_id),
                    "label": "Badge name",
                    "enabled": True,
                }
            ],
        )
        submission = self._submission(group)
        use_case, passport_repo = self._build_use_case(group, submission)

        await use_case.execute(
            submission.id,
            group_token=group.token,
            confirmed_fields={"passport_number": "P1234567"},
            client_email="person@example.com",
            client_phone="9876543210",
            designation="  Regional   Manager ",
            agency_dealership_name="  North   Motors ",
            custom_detail_answers=[
                {
                    "detail_id": str(detail_id),
                    "value": "  Nipun   V. ",
                }
            ],
        )

        self.assertEqual(
            submission.confirmed_fields["designation"],
            "Regional Manager",
        )
        self.assertEqual(
            submission.confirmed_fields["agency_dealership_name"],
            "North Motors",
        )
        self.assertEqual(
            submission.custom_detail_answers,
            [
                {
                    "detail_id": str(detail_id),
                    "label": "Badge name",
                    "value": "Nipun V.",
                }
            ],
        )
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
            ("agent_employee_type", {"agent_employee_code_enabled": True}),
            ("designation", {"designation_enabled": True}),
            (
                "agency_dealership_name",
                {"agency_dealership_name_enabled": True},
            ),
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
                "agent_employee_type": "agent",
                "agent_employee_code": "12345",
                "designation": "Injected",
                "agency_dealership_name": "Injected",
                "meal_preference": "Veg",
                "nearest_domestic_airport": "Injected",
            },
            client_email="person@example.com",
            client_phone="9876543210",
            departure_city="Injected",
            nearest_domestic_airport="Injected",
            base_city="Injected",
            staff_code="Injected",
            agent_employee_type="agent",
            agent_employee_code="12345",
            designation="Injected",
            agency_dealership_name="Injected",
            meal_preference="Veg",
        )

        self.assertIsNone(submission.departure_city)
        self.assertIsNone(submission.nearest_domestic_airport)
        self.assertNotIn("base_city", submission.confirmed_fields)
        self.assertNotIn("staff_code", submission.confirmed_fields)
        self.assertNotIn("agent_employee_type", submission.confirmed_fields)
        self.assertNotIn("agent_employee_code", submission.confirmed_fields)
        self.assertNotIn("designation", submission.confirmed_fields)
        self.assertNotIn("agency_dealership_name", submission.confirmed_fields)
        self.assertNotIn("meal_preference", submission.confirmed_fields)

    async def test_agent_employee_code_requires_numeric_value_up_to_ten_digits(self) -> None:
        group = self._group(agent_employee_code_enabled=True)
        for code in ("ABC123", "12345678901", "12 34"):
            with self.subTest(code=code):
                submission = self._submission(group)
                use_case, _ = self._build_use_case(group, submission)
                with self.assertRaises(ValidationError) as context:
                    await use_case.execute(
                        submission.id,
                        group_token=group.token,
                        confirmed_fields={"passport_number": "P1234567"},
                        client_email="person@example.com",
                        client_phone="9876543210",
                        agent_employee_type="employee",
                        agent_employee_code=code,
                    )
                self.assertEqual(context.exception.field, "agent_employee_code")

    async def test_agent_employee_code_requires_code_after_valid_type(self) -> None:
        group = self._group(agent_employee_code_enabled=True)
        submission = self._submission(group)
        use_case, _ = self._build_use_case(group, submission)

        with self.assertRaises(ValidationError) as context:
            await use_case.execute(
                submission.id,
                group_token=group.token,
                confirmed_fields={"passport_number": "P1234567"},
                client_email="person@example.com",
                client_phone="9876543210",
                agent_employee_type="agent",
            )

        self.assertEqual(context.exception.field, "agent_employee_code")

    async def test_exact_family_submit_replay_is_idempotent(self) -> None:
        group = self._group()
        submission = self._submission(group)
        use_case, passport_repo = self._build_use_case(group, submission)
        family_id = uuid.uuid4()
        request = {
            "group_token": group.token,
            "confirmed_fields": {"passport_number": "P1234567"},
            "client_email": None,
            "client_phone": None,
            "submission_mode": "family",
            "family_group_id": family_id,
            "family_member_index": 0,
            "family_relation": "Self",
            "family_gender": "Male",
            "family_head_name": "Family Head",
            "family_head_email": "head@example.com",
            "family_head_phone": "9876543210",
        }

        first = await use_case.execute(submission.id, **request)
        replay = await use_case.execute(submission.id, **request)

        self.assertFalse(first.idempotent_replay)
        self.assertTrue(replay.idempotent_replay)
        passport_repo.update.assert_awaited_once_with(submission)

        changed = {**request, "confirmed_fields": {"passport_number": "DIFFERENT"}}
        with self.assertRaises(ValidationError):
            await use_case.execute(submission.id, **changed)

    async def test_qualifier_submission_cannot_be_changed_to_family_mode(self) -> None:
        group = self._group()
        submission = self._submission(group)
        submission.qualifier_enabled_snapshot = True
        use_case, passport_repo = self._build_use_case(group, submission)

        with self.assertRaises(ValidationError) as context:
            await use_case.execute(
                submission.id,
                group_token=group.token,
                confirmed_fields={"passport_number": "P1234567"},
                client_email=None,
                client_phone=None,
                submission_mode="family",
                family_group_id=uuid.uuid4(),
                family_member_index=0,
                family_relation="Self",
                family_gender="Male",
                family_head_name="Family Head",
                family_head_email="head@example.com",
                family_head_phone="9876543210",
            )

        self.assertEqual(context.exception.field, "submission_mode")
        passport_repo.update.assert_not_awaited()

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
