"""Reject ambiguous API dates before comparison or PostgreSQL writes."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.presentation.api.v1.schemas.gc_app_schemas import (
    AnnouncementCreateRequest,
    GCGroupAccessUpdateRequest,
    ItineraryItemInput,
)


@pytest.mark.parametrize(("model", "payload", "field"), [
    (GCGroupAccessUpdateRequest, {"enabled": True}, "access_starts_at"),
    (GCGroupAccessUpdateRequest, {"enabled": True}, "access_expires_at"),
    (AnnouncementCreateRequest, {"title": "Test", "message": "Test", "expected_access_revision": 1}, "available_from"),
    (AnnouncementCreateRequest, {"title": "Test", "message": "Test", "expected_access_revision": 1}, "available_until"),
    (ItineraryItemInput, {"title": "Test"}, "starts_at"),
    (ItineraryItemInput, {"title": "Test"}, "ends_at"),
])
def test_timezone_is_required_on_operator_timestamp_inputs(model, payload, field):
    with pytest.raises(ValidationError) as error:
        model.model_validate({**payload, field: "2026-12-01T09:00:00"})
    assert error.value.errors()[0]["loc"] == (field,)
    assert error.value.errors()[0]["type"] == "timezone_aware"
    value = model.model_validate({**payload, field: "2026-12-01T09:00:00+05:30"})
    assert getattr(value, field).astimezone(UTC) == datetime(2026, 12, 1, 3, 30, tzinfo=UTC)


def test_access_window_compares_instants_across_timezones_and_rejects_naive_mix():
    with pytest.raises(ValidationError, match="after access start"):
        GCGroupAccessUpdateRequest.model_validate({
            "enabled": True, "access_starts_at": "2026-12-01T09:00:00+05:30",
            "access_expires_at": "2026-12-01T03:00:00Z",
        })
    with pytest.raises(ValidationError, match="timezone"):
        GCGroupAccessUpdateRequest.model_validate({
            "enabled": True, "access_starts_at": "2026-12-01T09:00:00",
            "access_expires_at": "2026-12-02T03:00:00Z",
        })
    assert GCGroupAccessUpdateRequest(enabled=True).access_starts_at is None
