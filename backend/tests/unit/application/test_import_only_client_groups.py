from __future__ import annotations

import uuid
from dataclasses import fields
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import UploadFile
from openpyxl import Workbook
from pydantic import ValidationError as SchemaValidationError

from app.application.dtos.client_group_dtos import CreateClientGroupInputDTO
from app.application.security.public_upload_capability import public_upload_is_active
from app.application.use_cases.client_groups.create_client_group_use_case import (
    CreateClientGroupUseCase,
)
from app.application.use_cases.client_groups.get_client_group_by_token_use_case import (
    GetClientGroupByTokenUseCase,
)
from app.domain.entities.entities import ClientGroup, UserRole
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.value_objects.import_group import import_group_settings
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.routes.passport_routes import excel_import
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
    CreateClientGroupRequest,
)


def minimal_request(**overrides):
    return CreateClientGroupRequest.model_validate({
        "import_only": True,
        "name": "Final Dubai passengers",
        "destination": "Dubai",
        "travel_date": "2026-11-10",
        "return_date": "2026-11-15",
        "timezone": "Asia/Kolkata",
        **overrides,
    })


def make_group(**overrides):
    return ClientGroup.create(
        name="Final Dubai passengers", token="internal-import-token",
        agency_id=uuid.uuid4(), created_by_user_id=uuid.uuid4(),
        import_only=True, **overrides,
    )


def test_import_mode_discards_invalid_hidden_collection_fields():
    request = minimal_request(
        nearest_international_airport_enabled=True, departure_cities=[],
        custom_questions=[{"label": "Unfinished question"}],
        upload_configuration={"passport_upload_pages": ["invalid-page"]},
        whatsapp_broadcast_group_ids=["not-a-uuid"],
        matching_fields_by_broadcast={"not-a-uuid": ["unfinished"]},
    )
    assert request.whatsapp_broadcast_group_ids == []
    assert request.matching_fields_by_broadcast is None
    for key, value in import_group_settings().items():
        assert request.model_dump()[key] == value


@pytest.mark.parametrize("overrides", [
    {"name": " "}, {"destination": ""}, {"travel_date": ""},
    {"return_date": "2026-11-09"}, {"timezone": "Mars/Unknown"},
])
def test_import_mode_still_validates_group_details(overrides):
    with pytest.raises(SchemaValidationError):
        minimal_request(**overrides)


def test_standard_mode_retains_collection_validation():
    with pytest.raises(SchemaValidationError):
        minimal_request(import_only=False, nearest_international_airport_enabled=True)
    request = minimal_request(import_only=False)
    assert request.allow_files_from_device is True
    assert request.upload_configuration is None


@pytest.mark.asyncio
async def test_import_mode_survives_creation_storage_and_response():
    request = minimal_request()
    values = request.model_dump()
    dto = CreateClientGroupInputDTO(**{f.name: values[f.name] for f in fields(CreateClientGroupInputDTO)})
    repo = AsyncMock()
    repo.save.side_effect = lambda group: group
    output = await CreateClientGroupUseCase(repo).execute(dto, uuid.uuid4(), uuid.uuid4())
    stored = ClientGroupRepository._to_model(repo.save.call_args.args[0])
    restored = ClientGroupRepository._to_entity(stored)
    assert restored.import_only is True
    assert restored.is_active()
    assert restored.upload_configuration["passport_enabled"] is False
    assert ClientGroupResponse.model_validate(output).import_only is True
    assert output.destination == "Dubai"
    assert output.travel_date == date(2026, 11, 10)
    assert output.timezone == "Asia/Kolkata"


def test_metadata_edits_cannot_reenable_import_group_public_collection():
    group = make_group(nearest_international_airport_enabled=True)
    group.update_configuration(
        name="Renamed trip", destination="Abu Dhabi", travel_date=None, return_date=None,
        timezone="Asia/Dubai", **{
            **import_group_settings(),
            "nearest_international_airport_enabled": True,
            "require_selfie": True,
            "allow_files_from_device": True,
            "upload_configuration": {"passport_enabled": True},
        },
    )
    assert group.name == "Renamed trip"
    assert group.timezone == "Asia/Dubai"
    assert group.import_only
    for key, value in import_group_settings().items():
        assert getattr(group, key) == value


@pytest.mark.asyncio
async def test_import_groups_grant_no_public_upload_capabilities():
    group = make_group()
    assert not public_upload_is_active(group)
    repo = AsyncMock()
    repo.get_by_token.return_value = group
    with pytest.raises(EntityNotFoundError):
        await GetClientGroupByTokenUseCase(repo).execute(group.token)


@pytest.mark.asyncio
async def test_staff_excel_import_works_with_collection_disabled(monkeypatch):
    group = make_group()
    user = SimpleNamespace(id=uuid.uuid4(), agency_id=group.agency_id,
                           role=UserRole.AGENCY_ADMIN, email="staff@example.test")
    rows_result = Mock()
    rows_result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = rows_result
    session.add_all = Mock()
    monkeypatch.setattr(excel_import, "ClientGroupRepository", lambda _: SimpleNamespace(get_by_id=AsyncMock(return_value=group)))
    monkeypatch.setattr(excel_import, "AuthorizationPolicy", lambda _: SimpleNamespace(require_export_data=AsyncMock()))
    monkeypatch.setattr(excel_import, "_lock_and_reauthorize_passport_excel_import", AsyncMock(return_value=(user, group)))
    monkeypatch.setattr(excel_import, "SqlAlchemyGroupPassengerCapacityGuard", lambda _: SimpleNamespace(assert_available=AsyncMock()))
    monkeypatch.setattr(excel_import, "propagate_mobile_passenger_change", AsyncMock())
    monkeypatch.setattr(excel_import, "AuditLogRepository", lambda _: SimpleNamespace(record=AsyncMock()))
    workbook = Workbook()
    workbook.active.append(["Staff Name", "PASSPORT_NO"])
    workbook.active.append(["ASHA RAO", "P1234567"])
    content = BytesIO()
    workbook.save(content)
    workbook.close()
    content.seek(0)

    result = await excel_import.import_passports_by_group(
        group.id, UploadFile(file=content, filename="final-passengers.xlsx"), user, session,
    )

    assert result.imported_count == 1
    assert result.updated_count == 0
    submission = session.add_all.call_args.args[0][0]
    assert submission.group_id == group.id
    assert submission.client_name == "ASHA RAO"
    assert submission.confirmed_fields["passport_number"] == "P1234567"
    session.commit.assert_awaited_once()
