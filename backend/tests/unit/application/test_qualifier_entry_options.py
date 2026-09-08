from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError as SchemaValidationError

from app.application.dtos.client_group_dtos import client_group_output_from_entity
from app.application.use_cases.client_groups.create_qualifier_selection_use_case import (
    CreateQualifierSelectionUseCase,
)
from app.application.use_cases.client_groups.get_qualifier_selection_use_case import (
    GetQualifierSelectionUseCase,
)
from app.domain.entities.entities import ClientGroup, QualifierSelection
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.qualifier_relations import normalize_qualifier_choice
from app.domain.value_objects.upload_configuration import configuration_for
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.schemas.client_group_schemas import CreateQualifierSelectionRequest


def group(*, listed=True, other=False, enabled=True):
    return ClientGroup.create(
        name="Relationship test", token="public-qualifier-token", agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(), relation_with_qualifier_enabled=enabled,
        upload_configuration={"qualifier_relation_list_enabled": listed, "qualifier_relation_other_enabled": other},
    )


@pytest.mark.parametrize("listed,other", [(True, False), (False, True), (True, True)])
def test_configured_methods_survive_database_mapping_and_options_are_only_listed(listed, other):
    link = ClientGroupRepository._to_entity(ClientGroupRepository._to_model(group(listed=listed, other=other)))
    config = configuration_for(link)
    assert config.qualifier_relation_list_enabled is listed
    assert config.qualifier_relation_other_enabled is other
    options = client_group_output_from_entity(link).qualifier_relation_options
    assert bool(options) is listed
    assert "other" not in {option["code"] for option in options}


def test_legacy_defaults_and_disabled_parent_hide_relationship_choices():
    link = group(enabled=False)
    link.upload_configuration = None
    assert configuration_for(link).qualifier_relation_list_enabled is True
    assert configuration_for(link).qualifier_relation_other_enabled is False
    assert client_group_output_from_entity(link).qualifier_relation_options == []


def test_enabled_parent_requires_at_least_one_method():
    with pytest.raises(ValidationError, match="at least one"):
        group(listed=False, other=False)
    assert group(listed=False, other=False, enabled=False)


@pytest.mark.parametrize("listed,other,code,text,allowed", [
    (True, False, "spouse", None, True),
    (True, False, "other", "Cousin", False),
    (False, True, "spouse", None, False),
    (False, True, "other", "Cousin", True),
    (True, True, "other", "Cousin", True),
    (True, True, "spouse", None, True),
    (False, True, None, None, True),
])
async def test_current_settings_enforce_each_creation_method(listed, other, code, text, allowed):
    link = group(listed=listed, other=other)
    links, selections = AsyncMock(), AsyncMock()
    links.get_by_token.return_value = link
    use_case = CreateQualifierSelectionUseCase(links, selections)
    args = dict(group_token=link.token, is_self=code is None, relation_code=code, other_relation=text)
    if allowed:
        result = await use_case.execute(**args)
        assert result.relation_code == code
        assert selections.save.await_count == 1
    else:
        with pytest.raises(ValidationError, match="no longer enabled"):
            await use_case.execute(**args)
        selections.save.assert_not_awaited()


@pytest.mark.parametrize("text", [None, "", "   ", "x" * 101, "Self", " SELF ", "Co\nworker", "Co\u200bworker", "Business\u2028partner", "Business\u2029partner"])
def test_custom_input_rejected_in_schema_and_domain(text):
    with pytest.raises(ValidationError):
        normalize_qualifier_choice(is_self=False, relation_code="other", other_relation=text)
    with pytest.raises(SchemaValidationError):
        CreateQualifierSelectionRequest(is_self=False, relation_code="other", other_relation=text)


@pytest.mark.parametrize("code,is_self", [("spouse", False), (None, True)])
def test_text_cannot_be_smuggled_alongside_other_selection_paths(code, is_self):
    with pytest.raises(SchemaValidationError):
        CreateQualifierSelectionRequest(is_self=is_self, relation_code=code, other_relation="Cousin")


def test_normalized_unicode_custom_relation_and_full_length_are_preserved():
    result = CreateQualifierSelectionRequest(is_self=False, relation_code="other", other_relation="  Fiance\u0301  ")
    assert result.other_relation == "Fiancé"
    assert normalize_qualifier_choice(is_self=False, relation_code="other", other_relation="a" * 100)[2] == "a" * 100


async def test_other_resumes_with_custom_label_and_rechecks_disabled_method_except_consumed():
    link = group(other=True)
    links, selections = AsyncMock(), AsyncMock()
    links.get_by_token.return_value = link
    now = datetime.now(tz=UTC)
    selection = QualifierSelection.create(
        group_id=link.id, token_hash="a" * 64, is_self=False, relation_code="other",
        other_relation="  Business partner  ", selected_at=now, expires_at=now + timedelta(hours=1),
    )
    selections.get_by_token_hash.return_value = selection
    selections.get_submission_id.return_value = None
    use_case = GetQualifierSelectionUseCase(links, selections)
    request = dict(group_token=link.token, selection_token="s" * 43)
    assert (await use_case.execute(**request)).relation_label == "Business partner"
    link.upload_configuration["qualifier_relation_other_enabled"] = False
    with pytest.raises(ValidationError, match="no longer enabled"):
        await use_case.execute(**request)
    selections.get_submission_id.return_value = uuid.uuid4()
    consumed = await use_case.execute(**request)
    assert consumed.status == "consumed"
    assert consumed.relation_label == "Business partner"
