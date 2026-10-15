import uuid
from copy import deepcopy
from types import SimpleNamespace

from app.application.platform_policies import PlatformPolicies
from app.application.travellers.requirements import requirement_signatures, saved_current_answers
from app.infrastructure.database.models import ClientGroupModel


def group():
    return ClientGroupModel(id=uuid.uuid4(), custom_questions=[{
        "id": str(uuid.uuid4()), "label": "Meal", "options": ["Veg", "Jain"], "enabled": True, "required": True,
    }], custom_details=[], base_city_enabled=False, staff_code_enabled=False,
        ask_nearest_domestic_airport=False, agent_employee_code_enabled=False, designation_enabled=False,
        agency_dealership_name_enabled=False, meal_preference_enabled=False,
        nearest_international_airport_enabled=False, departure_cities=[], upload_configuration=None)


def test_added_required_question_keeps_only_unchanged_answers_in_this_trip():
    trip = group()
    policies = PlatformPolicies()
    previous_id = trip.custom_questions[0]["id"]
    member = SimpleNamespace(group_id=trip.id, status="submitted",
        confirmations={"requirement_signatures": requirement_signatures(trip, policies)},
        answers={"custom_answers": [{"question_id": previous_id, "value": "Veg"}], "current_details": {"client_email": "person@example.invalid"}})
    changed = deepcopy(trip.custom_questions)
    changed.append({"id": str(uuid.uuid4()), "label": "New required question", "options": ["Yes", "No"], "required": True, "enabled": True})
    trip.custom_questions = changed
    saved = saved_current_answers(member, trip, policies)
    assert saved["custom_answers"] == {previous_id: "Veg"}
    assert saved["current_details"] == {"client_email": "person@example.invalid"}
    trip.custom_questions = [{**changed[0], "options": ["Different"]}, changed[1]]
    assert saved_current_answers(member, trip, policies)["custom_answers"] == {}
    trip.id = uuid.uuid4()
    assert all(not section for section in saved_current_answers(member, trip, policies).values())


def test_unknown_legacy_requirement_snapshot_does_not_supply_answers():
    trip = group()
    member = SimpleNamespace(group_id=trip.id, status="submitted", confirmations={},
        answers={"current_details": {"client_email": "old@example.invalid"}})
    assert all(not section for section in saved_current_answers(member, trip, PlatformPolicies()).values())
