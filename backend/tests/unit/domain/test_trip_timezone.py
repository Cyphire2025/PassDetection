from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.domain.entities.entities import ClientGroup
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.trip_timezone import (
    DEFAULT_TRIP_TIMEZONE,
    normalize_trip_timezone,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    CreateClientGroupRequest,
    UpdateClientGroupRequest,
)


def test_normalize_trip_timezone_accepts_iana_identifiers_and_rejects_offsets() -> None:
    assert normalize_trip_timezone("Asia/Singapore") == "Asia/Singapore"
    assert normalize_trip_timezone(" Asia/Kolkata ") == DEFAULT_TRIP_TIMEZONE

    for invalid in ("", "UTC+05:30", "Mars/Olympus_Mons", "x" * 65):
        with pytest.raises(ValueError):
            normalize_trip_timezone(invalid)


def test_client_group_owns_a_validated_canonical_timezone() -> None:
    group = ClientGroup.create(
        token="timezone-contract-token",
        agency_id=uuid.uuid4(),
        name="Singapore group",
        created_by_user_id=uuid.uuid4(),
        timezone="Asia/Singapore",
    )

    assert group.timezone == "Asia/Singapore"
    with pytest.raises(ValidationError, match="valid IANA timezone") as error:
        ClientGroup.create(
            token="invalid-timezone-token",
            agency_id=uuid.uuid4(),
            name="Invalid timezone group",
            created_by_user_id=uuid.uuid4(),
            timezone="Singapore Standard Time",
        )
    assert error.value.field == "timezone"


def test_create_and_update_api_contracts_default_validate_and_forbid_null() -> None:
    create = CreateClientGroupRequest(
        name="Default timezone group",
        destination="Delhi",
        travel_date=date(2026, 10, 1),
        return_date=date(2026, 10, 5),
    )
    assert create.timezone == DEFAULT_TRIP_TIMEZONE

    update = UpdateClientGroupRequest(name="Updated", timezone="Europe/Paris")
    assert update.timezone == "Europe/Paris"

    with pytest.raises(PydanticValidationError, match="Trip timezone cannot be null"):
        UpdateClientGroupRequest(name="Updated", timezone=None)
    with pytest.raises(PydanticValidationError, match="valid IANA timezone"):
        UpdateClientGroupRequest(name="Updated", timezone="Europe/Atlantis")
