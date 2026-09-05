from __future__ import annotations

import uuid
import zipfile
from unittest.mock import AsyncMock

import pytest

from app.application.dtos.client_group_dtos import client_group_output_from_entity
from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.export.passport_image_zip_exporter import PassportImageZipExporter
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.presentation.api.v1.schemas.client_group_schemas import ClientGroupResponse
from app.presentation.api.v1.schemas.passport_schemas import PassportSubmissionResponse


def group(**kwargs):
    return ClientGroup.create(
        name="Sample Trip",
        token="sample-trip-token",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        **kwargs,
    )


def test_configuration_survives_database_mapping_and_public_response():
    original = group(
        upload_configuration={
            "passport_upload_pages": ["back", "cover", "front", "back_cover"],
            "passport_live_scan": False,
            "required_fields": {"base_city": False, "staff_code": True},
            "agent_employee_code_label": "Producer Code",
        }
    )
    model = ClientGroupRepository._to_model(original)
    restored = ClientGroupRepository._to_entity(model)
    response = ClientGroupResponse.model_validate(client_group_output_from_entity(restored))
    assert response.upload_configuration.passport_upload_pages == [
        "cover",
        "back_cover",
        "front",
        "back",
    ]
    assert response.upload_configuration.required_fields["base_city"] is False
    assert response.upload_configuration.agent_employee_code_label == "Producer Code"


def test_old_links_retain_null_configuration_and_live_scanning_rules():
    original = group(allow_files_from_device=False)
    assert (
        ClientGroupRepository._to_entity(
            ClientGroupRepository._to_model(original)
        ).upload_configuration
        is None
    )
    assert original.require_allowed_acquisition_mode("camera") == "camera"
    with pytest.raises(ValidationError):
        original.require_allowed_acquisition_mode("file")


def test_group_edits_preserve_omitted_collection_configuration_and_optional_custom_fields():
    original = group(
        upload_configuration={"passport_upload_pages": ["cover", "front", "back"], "agent_employee_code_label": "Producer Code"},
        custom_details=[{"id": str(uuid.uuid4()), "label": "Badge name", "enabled": True, "required": False}],
        custom_questions=[{"id": str(uuid.uuid4()), "label": "Shirt size", "options": ["Small", "Large"], "enabled": True, "required": False}],
    )
    expected_configuration = dict(original.upload_configuration)
    original.update_configuration(
        name="Renamed trip", destination=None, travel_date=None, return_date=None,
        timezone=original.timezone, package_name=None, departure_cities=None,
        base_city_enabled=False, nearest_international_airport_enabled=False,
        staff_code_enabled=False, agent_employee_code_enabled=False, meal_preference_enabled=False,
        require_selfie=False, allow_files_from_device=True, ask_nearest_domestic_airport=False,
        relation_with_qualifier_enabled=False, designation_enabled=False, agency_dealership_name_enabled=False,
        custom_questions=None, custom_details=None, notes=None,
    )
    restored = ClientGroupRepository._to_entity(ClientGroupRepository._to_model(original))
    response = ClientGroupResponse.model_validate(client_group_output_from_entity(restored))
    assert response.name == "Renamed trip"
    assert response.upload_configuration.model_dump(mode="json") == expected_configuration
    assert response.custom_details[0].required is False
    assert response.custom_questions[0].required is False


@pytest.mark.parametrize(
    "configuration,kwargs",
    [
        ({"passport_live_scan": False}, {"allow_files_from_device": False}),
        ({"passport_upload_pages": []}, {}),
        ({"visa_photo_live_capture": False, "visa_photo_upload": False}, {"require_selfie": True}),
    ],
)
def test_creation_rejects_unusable_enabled_sections(configuration, kwargs):
    with pytest.raises(ValidationError):
        group(upload_configuration=configuration, **kwargs)


@pytest.mark.asyncio
async def test_cover_only_submission_roundtrips_and_exports_without_invented_front():
    configured = group(upload_configuration={"passport_upload_pages": ["cover", "back_cover"]})
    submission = PassportSubmission.create(
        group_id=configured.id,
        agency_id=configured.agency_id,
        client_name="Sample Traveller",
        client_email=None,
        image_s3_key="",
    )
    submission.promote_passport_cover("private/front-cover.jpg")
    submission.promote_passport_back_cover("private/back-cover.jpg")
    submission.prepare_without_passport_front()
    restored = PassportSubmissionRepository._to_entity(
        PassportSubmissionRepository._to_model(submission)
    )
    assert restored.image_s3_key == ""
    assert restored.passport_cover_s3_key == "private/front-cover.jpg"
    assert restored.passport_back_cover_s3_key == "private/back-cover.jpg"
    assert passport_storage_keys([restored]) == [
        "private/front-cover.jpg",
        "private/back-cover.jpg",
    ]
    storage = AsyncMock()
    storage.get_file.side_effect = lambda key: key.encode()
    spool, count, size = await PassportImageZipExporter().export_group(
        [restored],
        group_name=configured.name,
        staff_code_enabled=False,
        storage=storage,
        require_both_pages=False,
    )
    try:
        with zipfile.ZipFile(spool) as archive:
            files = [name for name in archive.namelist() if not name.endswith("/")]
            assert count == 2
            assert size > 0
            assert any(name.endswith("_passportcover.jpg") for name in files)
            assert any(name.endswith("_passportbackcover.jpg") for name in files)
            assert not any("passportfront" in name for name in files)
    finally:
        spool.close()


def test_no_passport_review_is_explicitly_unverified_and_labels_keep_existing_metadata():
    configured = group(upload_configuration={"passport_enabled": False})
    submission = PassportSubmission.create(
        group_id=configured.id,
        agency_id=configured.agency_id,
        client_name="Sample Traveller",
        client_email=None,
        image_s3_key="",
    )
    submission.staff_metadata = {"staff_code": "0021"}
    submission.snapshot_collection_labels(
        agent_employee_code_label="Producer Code", agency_dealership_name_label=None
    )
    submission.mark_no_passport_verification_required()
    response = PassportSubmissionResponse.model_validate(
        passport_submission_output_from_entity(submission)
    )
    assert response.status == "needs_review"
    assert response.post_submission_verified_at is None
    assert response.post_submission_verification.provider_status == "not_applicable"
    assert response.staff_metadata == {
        "staff_code": "0021",
        "agent_employee_code_label": "Producer Code",
    }
