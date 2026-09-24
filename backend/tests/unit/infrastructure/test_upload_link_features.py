from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.application.dtos.client_group_dtos import client_group_output_from_entity
from app.domain.entities.entities import ClientGroup
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.import_group import import_group_settings
from app.domain.value_objects.upload_configuration import UploadConfiguration, configuration_for
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.schemas.client_group_schemas import ClientGroupResponse


def make_group(configuration=None, **options):
    return ClientGroup.create(
        name="Instruction test group", token="instruction-test-token",
        agency_id=uuid.uuid4(), created_by_user_id=uuid.uuid4(),
        upload_configuration=configuration, **options,
    )


def test_existing_links_default_to_no_ecr_and_english_only():
    group = make_group()
    assert group.upload_configuration is None
    config = configuration_for(group)
    assert not config.passport_ecr_enabled
    assert not config.instruction_languages_enabled
    assert config.instruction_languages == []


def test_ecr_and_languages_survive_storage_public_response_and_group_edits():
    group = make_group({
        "passport_ecr_enabled": True,
        "instruction_languages_enabled": True,
        "instruction_languages": ["ta", "hi", "mr"],
    })
    restored = ClientGroupRepository._to_entity(ClientGroupRepository._to_model(group))
    response = ClientGroupResponse.model_validate(client_group_output_from_entity(restored))
    assert response.upload_configuration.passport_ecr_enabled is True
    assert response.upload_configuration.instruction_languages == ["mr", "hi", "ta"]
    assert response.upload_configuration.instruction_languages_enabled is True
    restored.upload_configuration = {**restored.upload_configuration, "passport_ecr_enabled": False}
    assert not configuration_for(restored).passport_ecr_enabled
    assert configuration_for(restored).instruction_languages == ["mr", "hi", "ta"]


@pytest.mark.parametrize("languages", [["en"], ["fr"], ["HI"], ["hi", "hi"]])
def test_only_distinct_supported_additional_languages_are_accepted(languages):
    with pytest.raises(PydanticValidationError):
        UploadConfiguration(instruction_languages_enabled=True, instruction_languages=languages)


def test_all_ten_languages_can_be_selected_with_english_remaining_implicit():
    codes = ["mr", "hi", "te", "kn", "gu", "bn", "or", "ml", "ta", "ur"]
    config = UploadConfiguration(
        instruction_languages_enabled=True, instruction_languages=list(reversed(codes)),
    )
    assert config.instruction_languages == codes


def test_language_switch_requires_a_selection_but_off_preserves_previous_choices():
    with pytest.raises(PydanticValidationError, match="at least one"):
        UploadConfiguration(instruction_languages_enabled=True)
    config = UploadConfiguration(instruction_languages_enabled=False, instruction_languages=["ur"])
    assert config.instruction_languages == ["ur"]


def test_ecr_requires_passport_collection_and_an_uploadable_back_page():
    with pytest.raises(ValidationError, match="passport collection"):
        make_group({"passport_enabled": False, "passport_ecr_enabled": True})
    with pytest.raises(ValidationError, match="address details page"):
        make_group({"passport_ecr_enabled": True, "passport_upload_pages": ["front"]})
    # Camera acquisition already requires the front and back, independently of
    # the unused file page list when file uploads are disabled.
    camera_group = make_group(
        {"passport_ecr_enabled": True, "passport_upload_pages": []}, allow_files_from_device=False,
    )
    assert configuration_for(camera_group).passport_ecr_enabled


def test_import_only_groups_do_not_enable_collection_features():
    config = UploadConfiguration.model_validate(import_group_settings()["upload_configuration"])
    assert not config.passport_ecr_enabled
    assert not config.instruction_languages_enabled
    assert config.instruction_languages == []
