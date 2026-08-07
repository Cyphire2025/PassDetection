"""Canonical document-distribution lanes and their external projections.

The stored identifiers in this module are an additive compatibility contract.
In particular, the two original flight-ticket identifiers continue to mean
International Onward and International Return so existing production rows do
not need to be rewritten during the taxonomy rollout.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

DocumentFamily = Literal["visa", "flight_ticket", "other"]
TravelScope = Literal["international", "domestic"]
JourneyDirection = Literal["onward", "return"]

VISA_DOCUMENT_TYPE = "visa"
INTERNATIONAL_ONWARD_DOCUMENT_TYPE = "flight_ticket"
INTERNATIONAL_RETURN_DOCUMENT_TYPE = "flight_ticket_arrival"
DOMESTIC_ONWARD_DOCUMENT_TYPE = "flight_ticket_domestic"
DOMESTIC_RETURN_DOCUMENT_TYPE = "flight_ticket_domestic_arrival"
OTHER_DOCUMENT_TYPE = "other"


@dataclass(frozen=True, slots=True)
class TravelDocumentLane:
    """One persisted distribution lane and its stable product semantics."""

    document_type: str
    family: DocumentFamily
    classifier_document_type: str
    label: str
    default_message_content: str
    mobile_category: str
    travel_scope: TravelScope | None = None
    journey_direction: JourneyDirection | None = None


_TRAVEL_DOCUMENT_LANES = (
    TravelDocumentLane(
        document_type=VISA_DOCUMENT_TYPE,
        family="visa",
        classifier_document_type="visa",
        label="Visa",
        default_message_content="This is your attached VISA",
        mobile_category="visa",
    ),
    TravelDocumentLane(
        document_type=INTERNATIONAL_ONWARD_DOCUMENT_TYPE,
        family="flight_ticket",
        classifier_document_type="flight_ticket",
        label="International Onward Flight Ticket",
        default_message_content="This is your attached INTERNATIONAL ONWARD FLIGHT TICKET",
        mobile_category="flight_ticket",
        travel_scope="international",
        journey_direction="onward",
    ),
    TravelDocumentLane(
        document_type=INTERNATIONAL_RETURN_DOCUMENT_TYPE,
        family="flight_ticket",
        classifier_document_type="flight_ticket",
        label="International Return Flight Ticket",
        default_message_content="This is your attached INTERNATIONAL RETURN FLIGHT TICKET",
        mobile_category="flight_ticket",
        travel_scope="international",
        journey_direction="return",
    ),
    TravelDocumentLane(
        document_type=DOMESTIC_ONWARD_DOCUMENT_TYPE,
        family="flight_ticket",
        classifier_document_type="flight_ticket",
        label="Domestic Onward Flight Ticket",
        default_message_content="This is your attached DOMESTIC ONWARD FLIGHT TICKET",
        mobile_category="flight_ticket",
        travel_scope="domestic",
        journey_direction="onward",
    ),
    TravelDocumentLane(
        document_type=DOMESTIC_RETURN_DOCUMENT_TYPE,
        family="flight_ticket",
        classifier_document_type="flight_ticket",
        label="Domestic Return Flight Ticket",
        default_message_content="This is your attached DOMESTIC RETURN FLIGHT TICKET",
        mobile_category="flight_ticket",
        travel_scope="domestic",
        journey_direction="return",
    ),
    TravelDocumentLane(
        document_type=OTHER_DOCUMENT_TYPE,
        family="other",
        classifier_document_type="other",
        label="Travel Document",
        default_message_content="This is your attached TRAVEL DOCUMENT",
        mobile_category="other",
    ),
)

TRAVEL_DOCUMENT_LANES = MappingProxyType(
    {lane.document_type: lane for lane in _TRAVEL_DOCUMENT_LANES}
)
DOCUMENT_TYPES = frozenset(TRAVEL_DOCUMENT_LANES)
SUPPORTED_TRAVEL_DOCUMENT_TYPES = frozenset({"visa", "flight_ticket"})
FLIGHT_TICKET_DOCUMENT_TYPES = frozenset(
    lane.document_type for lane in _TRAVEL_DOCUMENT_LANES if lane.family == "flight_ticket"
)
MOBILE_PERSONAL_DOCUMENT_TYPES = frozenset(
    {VISA_DOCUMENT_TYPE, *FLIGHT_TICKET_DOCUMENT_TYPES}
)


def document_lane(document_type: str) -> TravelDocumentLane | None:
    """Return the configured lane without silently accepting unknown values."""

    return TRAVEL_DOCUMENT_LANES.get(document_type)


def classification_document_type(document_type: str) -> str:
    """Map a persisted distribution lane to the class visible in the PDF."""

    lane = document_lane(document_type)
    return lane.classifier_document_type if lane is not None else document_type


def document_type_label(document_type: str) -> str:
    lane = document_lane(document_type)
    return lane.label if lane is not None else TRAVEL_DOCUMENT_LANES[OTHER_DOCUMENT_TYPE].label


def default_document_message(document_type: str) -> str:
    lane = document_lane(document_type)
    if lane is None:
        lane = TRAVEL_DOCUMENT_LANES[OTHER_DOCUMENT_TYPE]
    return lane.default_message_content


def mobile_document_category(document_type: str) -> str | None:
    lane = document_lane(document_type)
    return lane.mobile_category if lane is not None else None
