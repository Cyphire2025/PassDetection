"""Staff corrections preserve verified passports and refresh exact roster matching."""

from __future__ import annotations

import copy
import uuid

import pytest
from pydantic import ValidationError as SchemaValidationError

from app.application.use_cases.passports.client_details_fields import client_details_payload
from app.application.use_cases.passports.correct_client_details import correct_client_details
from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionForComparison,
    _submission_field_map,
)
from app.domain.entities.entities import ClientGroup, PassportProcessingStatus, PassportSubmission
from app.domain.exceptions.exceptions import ValidationError
from app.presentation.api.v1.schemas.passport_client_details_schemas import (
    PassportClientDetailsResponse,
    UpdatePassportClientDetailsRequest,
)


def sample():
    group = ClientGroup.create(
        name="Synthetic trip",
        agency_id=uuid.uuid4(),
        token="test-token-only",
        created_by_user_id=uuid.uuid4(),
    )
    group.agent_employee_code_enabled = True
    group.agency_dealership_name_enabled = True
    group.meal_preference_enabled = True
    group.departure_cities = ["Mumbai", "Delhi"]
    group.custom_questions = [
        {
            "id": str(uuid.uuid4()),
            "label": "Seating",
            "options": ["Aisle", "Window"],
            "enabled": True,
            "required": True,
        }
    ]
    group.custom_details = [
        {"id": str(uuid.uuid4()), "label": "Local office", "enabled": True, "required": False}
    ]
    submission = PassportSubmission.create(
        group.id, group.agency_id, "Test Traveller", "test@example.com", "safe/test.jpg"
    )
    submission.status = PassportProcessingStatus.AI_APPROVED
    submission.confirmed_fields = {
        "passport_number": "P1234567",
        "given_names": "Test Traveller",
        "agent_employee_code": "AIG12345",
        "meal_preference": "Veg",
    }
    submission.staff_metadata = {
        "agent_employee_code_label": "Producer Code",
        "agency_dealership_name_label": "Producer Name",
        "producer_code": "OLDER",
        "internal_note": "Retain this",
    }
    submission.extracted_fields = {"passport_number": "P1234567", "Producer Code": "OLD"}
    submission.post_submission_verification_revision = 4
    submission.post_submission_verification = {
        "verification_status": "approved",
        "confidence": 0.99,
    }
    submission.custom_answers = [
        {
            "question_id": group.custom_questions[0]["id"],
            "label": "Original seating label",
            "value": "Aisle",
        }
    ]
    submission.custom_detail_answers = [
        {
            "detail_id": group.custom_details[0]["id"],
            "label": "Original office label",
            "value": "East",
        }
    ]
    return submission, group


def test_descriptors_use_historical_labels_and_current_options():
    submission, group = sample()
    descriptor = PassportClientDetailsResponse.model_validate(
        client_details_payload(submission, group)
    )
    by_key = {field.key: field for field in descriptor.fields}
    assert by_key["agent_employee_code"].label == "Producer Code"
    assert by_key["agency_dealership_name"].label == "Producer Name"
    assert by_key["departure_city"].options == ["Mumbai", "Delhi"]
    assert descriptor.custom_answers[0].label == "Original seating label"
    assert descriptor.custom_answers[0].options == ["Aisle", "Window"]


def test_correct_code_does_not_touch_passport_or_verification_and_updates_aliases():
    submission, group = sample()
    before = copy.deepcopy(submission)
    updated, changed = correct_client_details(submission, group, {"agent_employee_code": "12345"})
    assert changed == ("agent_employee_code",)
    assert submission == before  # validation helper never mutates the loaded entity
    assert updated.confirmed_fields["agent_employee_code"] == "12345"
    assert updated.confirmed_fields["Producer Code"] == "12345"
    assert updated.staff_metadata["producer_code"] == "12345"
    assert updated.staff_metadata["internal_note"] == "Retain this"
    assert updated.extracted_fields == before.extracted_fields
    assert updated.status == before.status
    assert updated.post_submission_verification == before.post_submission_verification
    assert updated.post_submission_verification_revision == 4
    assert updated.extraction_revision == before.extraction_revision
    assert updated.image_s3_key == before.image_s3_key
    assert updated.confirmed_fields["passport_number"] == "P1234567"
    comparison = SubmissionForComparison(
        id=updated.id,
        name=updated.client_name,
        client_phone=None,
        client_email=updated.client_email,
        family_head_phone=None,
        updated_at=updated.updated_at,
        confirmed_fields=updated.confirmed_fields,
        extracted_fields=updated.extracted_fields,
        staff_metadata=updated.staff_metadata,
    )
    assert set(_submission_field_map(comparison)["agent_employee_code"]) == {"12345"}


def test_auxiliary_correction_preserves_extraction_only_passport_view():
    submission, group = sample()
    submission.confirmed_fields = None
    submission.extracted_fields = {
        "passport_number": "P7654321",
        "given_names": "Legacy Traveller",
        "date_of_birth": "1990-01-01",
        "producer_code": "OLD",
    }
    updated, _ = correct_client_details(submission, group, {"agent_employee_code": "12345"})
    assert updated.confirmed_fields["passport_number"] == "P7654321"
    assert updated.confirmed_fields["given_names"] == "Legacy Traveller"
    assert updated.confirmed_fields["date_of_birth"] == "1990-01-01"
    assert updated.extracted_fields == submission.extracted_fields
    assert updated.status == submission.status


def test_editor_effective_value_matches_confirmed_extracted_metadata_precedence():
    submission, group = sample()
    submission.confirmed_fields = None
    fields = client_details_payload(submission, group)["fields"]
    assert next(field.value for field in fields if field.key == "agent_employee_code") == "OLD"


def test_prefix_is_not_automatically_stripped():
    submission, group = sample()
    updated, _ = correct_client_details(submission, group, {"agent_employee_code": "AIG67890"})
    assert updated.confirmed_fields["agent_employee_code"] == "AIG67890"


def test_custom_answers_patch_by_id_preserves_unedited_and_saved_labels():
    submission, group = sample()
    retired_id = str(uuid.uuid4())
    submission.custom_detail_answers.append(
        {"detail_id": retired_id, "label": "Retired field", "value": "Keep"}
    )
    detail_id = group.custom_details[0]["id"]
    question_id = group.custom_questions[0]["id"]
    updated, changed = correct_client_details(
        submission,
        group,
        {
            "custom_answers": [{"question_id": question_id, "value": "window"}],
            "custom_detail_answers": [{"detail_id": detail_id, "value": " West "}],
        },
    )
    assert updated.custom_answers == [
        {"question_id": question_id, "label": "Original seating label", "value": "Window"}
    ]
    assert updated.custom_detail_answers == [
        {"detail_id": detail_id, "label": "Original office label", "value": "West"},
        {"detail_id": retired_id, "label": "Retired field", "value": "Keep"},
    ]
    assert len(changed) == 2


def test_optional_custom_clear_retains_editable_snapshot_and_disabled_answer_edit():
    submission, group = sample()
    item_id = group.custom_details[0]["id"]
    group.custom_details = []
    updated, _ = correct_client_details(
        submission, group, {"custom_detail_answers": [{"detail_id": item_id, "value": ""}]}
    )
    assert updated.custom_detail_answers[0]["value"] == ""
    assert (
        client_details_payload(updated, group)["custom_detail_answers"][0]["detail_id"] == item_id
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"passport_number": "MUTATED"},
        {"staff_metadata": {"role": "admin"}},
        {"status": "approved"},
        {"base_city": "Disabled field"},
        {"agent_employee_code": ""},
        {"meal_preference": "Invalid meal"},
        {"client_phone": "abc1234567"},
        {"client_phone": "12345"},
        {"departure_city": "Unknown airport"},
        {"custom_answers": [{"question_id": str(uuid.uuid4()), "value": "Window"}]},
    ],
)
def test_invalid_changes_do_not_mutate_any_fields(changes):
    submission, group = sample()
    before = copy.deepcopy(submission)
    with pytest.raises(ValidationError):
        correct_client_details(submission, group, changes)
    assert submission == before


def test_custom_ids_cannot_be_repeated_or_given_arbitrary_labels():
    submission, group = sample()
    item = {"question_id": group.custom_questions[0]["id"], "value": "Window"}
    for changes in (
        {"custom_answers": [item, item]},
        {"custom_answers": [{**item, "label": "Producer Code"}]},
    ):
        with pytest.raises(ValidationError):
            correct_client_details(submission, group, changes)


def test_invalid_custom_select_or_required_clear_rejected():
    submission, group = sample()
    for value in ("", "Unconfigured value"):
        with pytest.raises(ValidationError):
            correct_client_details(
                submission,
                group,
                {
                    "custom_answers": [
                        {"question_id": group.custom_questions[0]["id"], "value": value}
                    ]
                },
            )


def test_noop_keeps_revision_and_omitted_values():
    submission, group = sample()
    updated, changed = correct_client_details(submission, group, {"meal_preference": "veg"})
    assert updated == submission
    assert changed == ()


def test_corrected_contact_suppresses_legacy_matching_aliases():
    submission, group = sample()
    submission.client_phone = "9876543210"
    submission.confirmed_fields["phone"] = "9999999999"
    submission.staff_metadata["phone_number"] = "9999999999"
    updated, _ = correct_client_details(submission, group, {"client_phone": "+91 98765 43211"})
    assert updated.client_phone == "+919876543211"
    assert updated.confirmed_fields["phone"] == "+919876543211"
    assert updated.staff_metadata["phone_number"] == "+919876543211"


def test_corrected_airports_do_not_leave_old_imported_aliases_matchable():
    submission, group = sample()
    group.ask_nearest_domestic_airport = True
    submission.departure_city = "Mumbai"
    submission.nearest_domestic_airport = "Domestic A"
    submission.confirmed_fields["departure_city"] = "Mumbai"
    submission.extracted_fields["nearest_international_airport"] = "Mumbai"
    submission.staff_metadata["nearest_domestic_airport"] = "Domestic A"
    updated, _ = correct_client_details(
        submission, group, {"departure_city": "Delhi", "nearest_domestic_airport": "Domestic B"}
    )
    comparison = SubmissionForComparison(
        id=updated.id,
        name=updated.client_name,
        client_phone=None,
        family_head_phone=None,
        updated_at=updated.updated_at,
        departure_city=updated.departure_city,
        nearest_domestic_airport=updated.nearest_domestic_airport,
        confirmed_fields=updated.confirmed_fields,
        extracted_fields=updated.extracted_fields,
        staff_metadata=updated.staff_metadata,
    )
    assert set(_submission_field_map(comparison)["departure_city"]) == {"Delhi"}
    assert set(_submission_field_map(comparison)["nearest_international_airport"]) == {"Delhi"}
    assert set(_submission_field_map(comparison)["nearest_domestic_airport"]) == {"Domestic B"}


@pytest.mark.parametrize(
    "extra",
    [
        {"confirmed_fields": {"passport_number": "X"}},
        {"client_email": "not-an-email"},
        {"agent_employee_code": "x" * 81},
        {"custom_answers": None},
        {"custom_answers": [{"question_id": str(uuid.uuid4()), "label": "Spoofed", "value": "X"}]},
    ],
)
def test_patch_schema_forbids_unbounded_or_untrusted_fields(extra):
    submission, _ = sample()
    with pytest.raises(SchemaValidationError):
        UpdatePassportClientDetailsRequest.model_validate(
            {"expected_updated_at": submission.updated_at, **extra}
        )


def test_patch_schema_requires_aware_revision_and_at_least_one_field():
    submission, _ = sample()
    for payload in (
        {},
        {"expected_updated_at": submission.updated_at},
        {"expected_updated_at": "2026-09-10T11:22:33", "client_phone": "9876543210"},
    ):
        with pytest.raises(SchemaValidationError):
            UpdatePassportClientDetailsRequest.model_validate(payload)
