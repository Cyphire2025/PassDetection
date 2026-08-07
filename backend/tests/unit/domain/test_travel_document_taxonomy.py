from __future__ import annotations

from app.domain.value_objects.travel_document_taxonomy import (
    DOCUMENT_TYPES,
    DOMESTIC_ONWARD_DOCUMENT_TYPE,
    DOMESTIC_RETURN_DOCUMENT_TYPE,
    FLIGHT_TICKET_DOCUMENT_TYPES,
    INTERNATIONAL_ONWARD_DOCUMENT_TYPE,
    INTERNATIONAL_RETURN_DOCUMENT_TYPE,
    MOBILE_PERSONAL_DOCUMENT_TYPES,
    classification_document_type,
    document_lane,
)


def test_legacy_ticket_ids_keep_their_international_semantics() -> None:
    onward = document_lane(INTERNATIONAL_ONWARD_DOCUMENT_TYPE)
    returned = document_lane(INTERNATIONAL_RETURN_DOCUMENT_TYPE)

    assert onward is not None
    assert onward.travel_scope == "international"
    assert onward.journey_direction == "onward"
    assert returned is not None
    assert returned.travel_scope == "international"
    assert returned.journey_direction == "return"


def test_domestic_lanes_are_additive_and_classify_as_flight_tickets() -> None:
    assert DOMESTIC_ONWARD_DOCUMENT_TYPE in DOCUMENT_TYPES
    assert DOMESTIC_RETURN_DOCUMENT_TYPE in DOCUMENT_TYPES
    assert FLIGHT_TICKET_DOCUMENT_TYPES == {
        INTERNATIONAL_ONWARD_DOCUMENT_TYPE,
        INTERNATIONAL_RETURN_DOCUMENT_TYPE,
        DOMESTIC_ONWARD_DOCUMENT_TYPE,
        DOMESTIC_RETURN_DOCUMENT_TYPE,
    }
    assert classification_document_type(DOMESTIC_ONWARD_DOCUMENT_TYPE) == "flight_ticket"
    assert classification_document_type(DOMESTIC_RETURN_DOCUMENT_TYPE) == "flight_ticket"
    assert MOBILE_PERSONAL_DOCUMENT_TYPES == {"visa", *FLIGHT_TICKET_DOCUMENT_TYPES}
