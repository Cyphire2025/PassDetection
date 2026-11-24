"""Tracker API value projections from already-authorized canonical roster rows."""

from __future__ import annotations

from app.application.dtos.travel_tracker import (
    TrackerCounts,
    TrackerGroup,
    TrackerPassenger,
    TrackerTrack,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.travel_tracker_model import TravelTrackerModel
from app.infrastructure.travel_tracker.spreadsheet_values import field_values, full_name, text_value


def counts(summary: TrackerGroup, track: TrackerTrack) -> TrackerCounts:
    marked = summary.visa_marked if track == "visa" else summary.flight_marked
    return TrackerCounts(total=summary.total, marked=marked, pending=summary.total - marked)


def project_passenger(
    passenger: PassportSubmissionModel, tracker: TravelTrackerModel | None
) -> TrackerPassenger:
    fields = field_values(passenger)
    return TrackerPassenger(
        id=passenger.id,
        full_name=full_name(passenger),
        given_name=text_value(fields.get("given_names")),
        surname=text_value(fields.get("surname")),
        passport_number=text_value(fields.get("passport_number")),
        nationality=text_value(fields.get("nationality")),
        gender=text_value(fields.get("sex")),
        date_of_birth=text_value(fields.get("date_of_birth")),
        date_of_expiry=text_value(fields.get("date_of_expiry")),
        email=passenger.client_email,
        phone=passenger.client_phone,
        departure_city=passenger.departure_city,
        submission_status=passenger.status,
        visa_applied=bool(tracker and tracker.visa_applied),
        flight_booked=bool(tracker and tracker.flight_booked),
        visa_updated_at=tracker.visa_updated_at if tracker else None,
        flight_updated_at=tracker.flight_updated_at if tracker else None,
    )
