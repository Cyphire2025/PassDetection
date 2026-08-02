from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.infrastructure.rooming.priority_fields import (
    ROOMING_GENDER_RULE,
    build_rooming_priority_context,
    is_rooming_roster_field,
)


class _ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[object]:
        return self._values


class _RowsResult:
    def __init__(self, values: list[tuple[object, ...]]) -> None:
        self._values = values

    def all(self) -> list[tuple[object, ...]]:
        return self._values


class _Session:
    def __init__(self, results: list[object]) -> None:
        self._results = iter(results)

    async def execute(self, _statement: object) -> object:
        return next(self._results)


@pytest.mark.asyncio
async def test_catalog_includes_enabled_collected_fields_and_excludes_fixed_gender_aliases() -> None:
    broadcast_id = uuid.uuid4()
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        agency_dealership_name_enabled=True,
        base_city_enabled=True,
        ask_nearest_domestic_airport=True,
        nearest_international_airport_enabled=True,
        meal_preference_enabled=True,
        designation_enabled=True,
        relation_with_qualifier_enabled=True,
        custom_questions=[
            {"id": str(uuid.uuid4()), "label": "Team", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "Gender", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "DOB", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "PassengerGender", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "PassportNumber", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "AgeGroup", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "GivenName", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "PassengerSexField", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "Essex County", "enabled": True},
        ],
        custom_details=[
            {"id": str(uuid.uuid4()), "label": "Cost Centre", "enabled": True},
            {"id": str(uuid.uuid4()), "label": "Passenger Gender", "enabled": True},
        ],
    )
    recipient = SimpleNamespace(
        imported_fields={
            "Department": "Sales",
            "Zone": "North",
            "PASSPORT NUM": "P1",
            "PassportNum": "P1",
            "DOI": "2025-01-01",
            "DateOfIssue": "2025-01-01",
            "DOE": "2035-01-01",
            "DateOfExpiry": "2035-01-01",
            "PLACE OF ISSUE": "Delhi",
            "PlaceOfIssue": "Delhi",
            "GENDER": "Female",
            "Passenger Gender": "Female",
            "PassportNumber": "P1",
            "DateOfBirth": "2000-01-01",
            "GivenName": "Asha",
            "AgeGroup": "Adult",
            "AgentEmployeeCode": "EMP_1",
            "PassengerGender": "Female",
            "PassengerSexField": "Female",
            "Essex County": "North",
        }
    )
    session = _Session(
        [
            _RowsResult([(broadcast_id, "Roster")]),
            _ScalarResult([recipient]),
        ]
    )

    context = await build_rooming_priority_context(
        session,  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
        passengers=[],
    )
    labels = {field["label"] for field in context.fields}
    keys = {field["key"] for field in context.fields}

    assert {
        "Phone Number",
        "Email ID",
        "Nationality",
        "Submission Mode",
        "Family Relation",
        "Family / Couple",
        "Agency/Dealership Name",
        "Base City",
        "Domestic Airport",
        "International Airport",
        "Meal Preference",
        "Designation",
        "Relation with Qualifier",
        "Team",
        "Cost Centre",
        "Department",
        "Zone",
        "Essex County",
    }.issubset(labels)
    assert not {
        "PASSPORT NUM",
        "PassportNum",
        "DOI",
        "DateOfIssue",
        "DOE",
        "DateOfExpiry",
        "PLACE OF ISSUE",
        "PlaceOfIssue",
        "GENDER",
        "Passenger Gender",
        "DOB",
        "PassportNumber",
        "DateOfBirth",
        "GivenName",
        "AgeGroup",
        "AgentEmployeeCode",
        "PassengerGender",
        "PassengerSexField",
    } & labels
    assert "whatsapp:department" in keys
    assert "whatsapp:zone" in keys
    assert "whatsapp:essex_county" in keys
    assert "male passengers" in ROOMING_GENDER_RULE.casefold()
    assert "female passengers" in ROOMING_GENDER_RULE.casefold()


@pytest.mark.asyncio
async def test_priority_values_resolve_custom_group_and_matched_whatsapp_data() -> None:
    broadcast_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    question_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        agency_dealership_name_enabled=False,
        base_city_enabled=False,
        ask_nearest_domestic_airport=False,
        nearest_international_airport_enabled=False,
        meal_preference_enabled=True,
        designation_enabled=False,
        relation_with_qualifier_enabled=False,
        custom_questions=[
            {"id": str(question_id), "label": "Team", "enabled": True},
        ],
        custom_details=[],
    )
    recipient = SimpleNamespace(
        id=uuid.uuid4(),
        broadcast_group_id=broadcast_id,
        name="Asha",
        normalized_phone_number="+919999999999",
        created_at=now,
        imported_fields={"Department": "Sales"},
    )
    passenger = SimpleNamespace(
        id=passenger_id,
        client_name="Asha",
        client_phone="+919999999999",
        client_email="asha@example.com",
        family_head_phone=None,
        family_head_email=None,
        updated_at=now,
        confirmed_fields={"nationality": "Indian", "meal_preference": "Veg"},
        extracted_fields={},
        staff_metadata={},
        custom_answers=[
            {
                "question_id": str(question_id),
                "label": "Team",
                "value": "Alpha",
            }
        ],
        custom_detail_answers=[],
        family_head_name=None,
        family_group_id=None,
        family_relation=None,
        submission_mode="single",
        nearest_domestic_airport=None,
        departure_city=None,
        qualifier_relation_label=None,
        qualifier_enabled_snapshot=False,
    )
    session = _Session(
        [
            _RowsResult([(broadcast_id, "Roster")]),
            _ScalarResult([recipient]),
        ]
    )

    context = await build_rooming_priority_context(
        session,  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
        passengers=[passenger],  # type: ignore[list-item]
    )
    values = context.values_by_passenger[passenger_id]

    assert values["field:client_email"] == "asha@example.com"
    assert values["field:nationality"] == "Indian"
    assert values["field:meal_preference"] == "Veg"
    assert values[f"custom:{question_id}"] == "Alpha"
    assert values["whatsapp:department"] == "Sales"


@pytest.mark.asyncio
async def test_imported_metadata_catalog_is_safe_unicode_and_independently_resolved() -> None:
    passenger_id = uuid.uuid4()
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        agency_dealership_name_enabled=False,
        base_city_enabled=False,
        ask_nearest_domestic_airport=False,
        nearest_international_airport_enabled=False,
        meal_preference_enabled=False,
        designation_enabled=False,
        relation_with_qualifier_enabled=False,
        custom_questions=[],
        custom_details=[],
    )
    passenger = SimpleNamespace(
        id=passenger_id,
        client_name="Élodie",
        client_phone=None,
        client_email=None,
        family_head_phone=None,
        family_head_email=None,
        updated_at=datetime.now(tz=UTC),
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={
            "zone": "South",
            "État": "Tamil Nadu",
            "source_zone": "North",
            "client_name": "Must not leak",
            "mobile_number": "+919999999999",
            "WhatsApp Number": "+918888888888",
            "Whats App No": "+918888888887",
            "WA No": "+918888888884",
            "W/App No": "+918888888883",
            "Mob No": "+918888888882",
            "Ph No": "+918888888881",
            "Mail ID": "private@example.com",
            "Residential Addr": "Private address",
            "Employee ID": "EMP-1",
            "Emp ID": "EMP-2",
            "National ID": "ID-1",
            "Government ID": "ID-2",
            "Tax ID": "ID-3",
            "Customer ID": "ID-4",
            "Ｐｈｏｎｅ": "+918888888886",
            "phóne": "+918888888885",
            "telephone": "+917777777777",
            "contact": "+916666666666",
            "cell": "+915555555555",
            "passport_number": "P123",
            "home_address": "Private",
            "source_sheet": "Sheet 1",
            "x" * 200: "Must not create an unusable API key",
        },
        custom_answers=[],
        custom_detail_answers=[],
        family_head_name=None,
        family_group_id=None,
        family_relation=None,
        submission_mode="single",
        nearest_domestic_airport=None,
        departure_city=None,
        qualifier_relation_label=None,
        qualifier_enabled_snapshot=False,
    )
    context = await build_rooming_priority_context(
        _Session([_RowsResult([])]),  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
        passengers=[passenger],  # type: ignore[list-item]
        requested_keys=["metadata:zone", "metadata:état"],
    )

    metadata_fields = {
        field["key"]: field for field in context.fields
        if field["key"].startswith("metadata:")
    }
    assert set(metadata_fields) == {
        "metadata:source_zone",
        "metadata:zone",
        "metadata:état",
    }
    assert metadata_fields["metadata:état"]["label"] == "État"
    assert all(is_rooming_roster_field(field) for field in metadata_fields.values())
    assert not is_rooming_roster_field(
        {
            "key": "field:client_phone",
            "label": "Phone Number",
            "source": "contact",
        }
    )
    assert not is_rooming_roster_field(
        {
            "key": "whatsapp:whatsapp_number",
            "label": "WhatsApp Number",
            "source": "whatsapp",
        }
    )
    assert context.values_by_passenger[passenger_id] == {
        "metadata:zone": "South",
        "metadata:état": "Tamil Nadu",
    }


@pytest.mark.asyncio
async def test_catalog_only_and_local_field_resolution_skip_whatsapp_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broadcast_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        agency_dealership_name_enabled=False,
        base_city_enabled=False,
        ask_nearest_domestic_airport=False,
        nearest_international_airport_enabled=False,
        meal_preference_enabled=False,
        designation_enabled=False,
        relation_with_qualifier_enabled=False,
        custom_questions=[],
        custom_details=[],
    )
    passenger = SimpleNamespace(id=passenger_id, staff_metadata={"zone": "West"})
    recipient = SimpleNamespace(imported_fields={"Department": "Sales"})

    def fail_comparison(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("catalog/local resolution must not compare recipients")

    monkeypatch.setattr(
        "app.infrastructure.rooming.priority_fields.compare_group_submissions",
        fail_comparison,
    )
    catalog = await build_rooming_priority_context(
        _Session(
            [
                _RowsResult([(broadcast_id, "Roster")]),
                _ScalarResult([recipient]),
            ]
        ),  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
        passengers=[passenger],  # type: ignore[list-item]
        resolve_values=False,
    )
    assert catalog.values_by_passenger == {}
    assert "whatsapp:department" in {field["key"] for field in catalog.fields}

    passenger = SimpleNamespace(
        id=passenger_id,
        client_name="Asha",
        client_phone=None,
        client_email=None,
        family_head_phone=None,
        family_head_email=None,
        updated_at=datetime.now(tz=UTC),
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={"zone": "West"},
        custom_answers=[],
        custom_detail_answers=[],
        family_head_name=None,
        family_group_id=None,
        family_relation=None,
        submission_mode="single",
        nearest_domestic_airport=None,
        departure_city=None,
        qualifier_relation_label=None,
        qualifier_enabled_snapshot=False,
    )
    local = await build_rooming_priority_context(
        _Session(
            [
                _RowsResult([(broadcast_id, "Roster")]),
                _ScalarResult([recipient]),
            ]
        ),  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
        passengers=[passenger],  # type: ignore[list-item]
        requested_keys=["metadata:zone"],
    )
    assert local.values_by_passenger[passenger_id] == {
        "metadata:zone": "West"
    }
