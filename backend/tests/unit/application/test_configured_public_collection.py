from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.application.platform_policies import PlatformPolicies
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.upload_configuration import (
    validate_documents,
    validate_visa_photo_source,
)


def _group(config: dict | None = None, **options) -> ClientGroup:
    return ClientGroup.create(
        name="Synthetic configured upload",
        token="synthetic-configured-upload-link",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        upload_configuration=config,
        **options,
    )


def _upload(group):
    groups = AsyncMock()
    groups.get_by_token.return_value = group
    passports = AsyncMock()
    passports.save_idempotent.side_effect = lambda item: (item, True)
    storage = AsyncMock()
    jobs = AsyncMock()
    return SubmitPassportUseCase(groups, passports, storage, jobs), passports, storage, jobs


def _review(group, submission):
    groups = AsyncMock()
    groups.get_by_token.return_value = group
    passports = AsyncMock()
    passports.get_by_id_for_update.return_value = submission
    passports.exists_contact_in_group.return_value = False
    storage = AsyncMock()
    storage.get_file.return_value = b"synthetic image"
    policies = AsyncMock()
    policies.load.return_value = PlatformPolicies(require_client_email=False, require_client_phone=False)
    return ClientSubmitPassportUseCase(passports, groups, storage, policies), passports, storage


@pytest.mark.parametrize("config", [{"passport_enabled": False}, {"passport_required": False}])
async def test_no_passport_upload_persists_review_draft_without_storage_or_ocr(config):
    group = _group(config)
    use_case, passports, storage, jobs = _upload(group)
    result = await use_case.execute(
        token=group.token, file_content=b"", content_type="image/jpeg", filename="", client_name="Traveller",
    )
    assert result.image_s3_key == ""
    assert result.status == "ready_for_client_review"
    assert result.extraction_status == "ready_for_review"
    passports.save_idempotent.assert_awaited_once()
    storage.upload_file.assert_not_awaited()
    jobs.create.assert_not_awaited()


async def test_requested_covers_are_stored_and_promoted_without_ocr():
    group = _group({"passport_upload_pages": ["cover", "back_cover"]})
    use_case, passports, storage, jobs = _upload(group)
    result = await use_case.execute(
        token=group.token, file_content=b"", content_type="image/jpeg", filename="", client_name="Traveller",
        passport_cover=(b"synthetic cover", "image/jpeg", "cover.jpg"),
        passport_back_cover=(b"synthetic back cover", "image/jpeg", "back-cover.jpg"),
    )
    assert result.passport_cover_s3_key.endswith("-cover.jpg")
    assert result.passport_back_cover_s3_key.endswith("-back_cover.jpg")
    assert storage.upload_file.await_count == 2
    jobs.create.assert_not_awaited()
    submission = passports.save_idempotent.call_args.args[0]
    review, _, permanent_storage = _review(group, submission)
    final = await review.execute(
        submission.id, group_token=group.token, confirmed_fields={"given_names": "Synthetic Traveller"},
        client_email=None, client_phone=None,
    )
    assert final.status == "needs_review"
    assert final.post_submission_verified_at is None
    assert not final.passport_cover_s3_key.startswith("drafts/")
    assert not final.passport_back_cover_s3_key.startswith("drafts/")
    assert len(final.storage_cleanup_keys) == 2
    assert permanent_storage.upload_file.await_count == 2
    replay = await review.execute(
        submission.id, group_token=group.token, confirmed_fields={"given_names": "Synthetic Traveller"},
        client_email=None, client_phone=None,
    )
    assert replay.idempotent_replay
    assert permanent_storage.upload_file.await_count == 2


@pytest.mark.parametrize(
    ("config", "mode", "pages", "options", "message"),
    [
        ({"passport_enabled": False}, "file", {"front": b"image"}, {}, "disabled"),
        ({"passport_live_scan": False}, "camera", {"front": b"image", "back": b"image"}, {}, "disabled"),
        ({}, "file", {"front": b"image", "back": b"image"}, {"allow_files_from_device": False}, "scanning"),
        ({"passport_required": False}, "file", {"front": b"image"}, {}, "address details"),
        ({"passport_upload_pages": ["cover", "front", "back"]}, "file", {"front": b"image", "back": b"image"}, {}, "front cover"),
        ({}, "camera", {"front": b"image", "back": b"image", "cover": b"image"}, {}, "not requested"),
    ],
)
def test_passport_modes_and_selected_pages_are_authoritative(config, mode, pages, options, message):
    group = _group(config, **options)
    with pytest.raises(ValidationError, match=message):
        validate_documents(group, pages=pages, mode=mode, photo=None)


def test_live_scan_keeps_exact_front_and_back_when_file_upload_requests_covers():
    group = _group({"passport_upload_pages": ["cover", "back_cover", "front", "back"]})
    validate_documents(group, pages={"front": b"image", "back": b"image"}, mode="camera", photo=None)


@pytest.mark.parametrize(("config", "source"), [
    ({"visa_photo_live_capture": False}, "camera"),
    ({"visa_photo_upload": False}, "file"),
    ({"visa_photo_upload": False}, None),
])
def test_visa_photo_rejects_disabled_or_unspecified_restricted_method(config, source):
    group = _group(config, require_selfie=True)
    with pytest.raises(ValidationError):
        validate_visa_photo_source(group, photo=b"photo", source=source)


@pytest.mark.parametrize("required", [True, False])
def test_visa_photo_required_setting_controls_missing_photo(required):
    group = _group({"passport_enabled": False, "visa_photo_required": required}, require_selfie=True)
    if required:
        with pytest.raises(ValidationError, match="Visa Photo is required"):
            validate_documents(group, pages={}, mode="file", photo=None)
    else:
        validate_documents(group, pages={}, mode="file", photo=None)


@pytest.mark.parametrize(("field", "option"), [
    ("base_city", "base_city_enabled"),
    ("nearest_domestic_airport", "ask_nearest_domestic_airport"),
    ("departure_city", "nearest_international_airport_enabled"),
    ("staff_code", "staff_code_enabled"),
    ("agent_employee_code", "agent_employee_code_enabled"),
    ("designation", "designation_enabled"),
    ("agency_dealership_name", "agency_dealership_name_enabled"),
    ("meal_preference", "meal_preference_enabled"),
])
@pytest.mark.parametrize("required", [True, False])
async def test_each_configured_detail_enforces_its_own_required_setting(field, option, required):
    group = _group(
        {"passport_enabled": False, "required_fields": {field: required}},
        **{option: True, "departure_cities": ["Delhi"]},
    )
    submission = PassportSubmission.create(group.id, group.agency_id, "Traveller", None, "")
    use_case, passports, _ = _review(group, submission)
    kwargs = dict(group_token=group.token, confirmed_fields={"given_names": "Synthetic Traveller"}, client_email=None, client_phone=None)
    if required:
        with pytest.raises(ValidationError) as exc:
            await use_case.execute(submission.id, **kwargs)
        assert exc.value.field == field
        passports.update.assert_not_awaited()
    else:
        result = await use_case.execute(submission.id, **kwargs)
        assert result.status == "needs_review"


async def test_renamed_code_accepts_letters_without_role_and_snapshots_labels():
    group = _group(
        {"passport_enabled": False, "agent_employee_code_label": "Producer Code", "agency_dealership_name_label": "Production Company"},
        agent_employee_code_enabled=True, agency_dealership_name_enabled=True,
    )
    submission = PassportSubmission.create(group.id, group.agency_id, "Traveller", None, "")
    submission.staff_metadata = {"existing": "retained"}
    use_case, _, _ = _review(group, submission)
    result = await use_case.execute(
        submission.id, group_token=group.token, confirmed_fields={"given_names": "Synthetic Traveller"},
        client_email=None, client_phone=None, agent_employee_code="  PROD-42  ", agency_dealership_name="Example Productions",
    )
    assert result.confirmed_fields["agent_employee_code"] == "PROD-42"
    assert "agent_employee_type" not in result.confirmed_fields
    assert submission.staff_metadata == {
        "existing": "retained", "agent_employee_code_label": "Producer Code", "agency_dealership_name_label": "Production Company",
    }


async def test_present_front_retains_classification_gate_even_when_passport_optional():
    group = _group({"passport_required": False})
    submission = PassportSubmission.create(group.id, group.agency_id, "Traveller", None, "front.jpg")
    submission.passport_back_s3_key = "back.jpg"
    use_case, passports, _ = _review(group, submission)
    with pytest.raises(ValidationError, match="could not confirm"):
        await use_case.execute(
            submission.id, group_token=group.token, confirmed_fields={"given_names": "Synthetic Traveller"},
            client_email=None, client_phone=None,
        )
    passports.update.assert_not_awaited()


@pytest.mark.parametrize("required", [True, False])
async def test_qualifier_selection_can_be_optional_for_upload(required):
    group = _group(
        {"passport_enabled": False, "required_fields": {"relation_with_qualifier": required}},
        relation_with_qualifier_enabled=True,
    )
    use_case, passports, _, _ = _upload(group)
    kwargs = dict(token=group.token, file_content=b"", content_type="image/jpeg", filename="", client_name="Traveller")
    if required:
        with pytest.raises(ValidationError) as exc:
            await use_case.execute(**kwargs)
        assert exc.value.field == "qualifier_selection_token"
        passports.save_idempotent.assert_not_awaited()
    else:
        result = await use_case.execute(**kwargs)
        assert result.qualifier_enabled_snapshot is False


async def test_disabled_international_airport_does_not_require_stale_saved_choices():
    group = _group({"passport_enabled": False})
    group.departure_cities = ["Delhi"]
    submission = PassportSubmission.create(group.id, group.agency_id, "Traveller", None, "")
    use_case, _, _ = _review(group, submission)
    result = await use_case.execute(
        submission.id, group_token=group.token, confirmed_fields={"given_names": "Synthetic Traveller"},
        client_email=None, client_phone=None,
    )
    assert result.departure_city is None
