"""Runtime aliases and annotations used by HTTP and private MCP tracker adapters."""

from __future__ import annotations

import inspect
from typing import get_type_hints

from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.travel_tracker import (
    queries,
    service,
    spreadsheet_export,
    spreadsheet_matching,
    spreadsheet_reader,
    spreadsheet_values,
    spreadsheets,
)


def test_spreadsheet_facade_preserves_actual_public_and_compatibility_objects():
    owners = {
        spreadsheet_values: [
            "MAX_UPLOAD_BYTES",
            "MAX_IMPORT_ROWS",
            "MAX_EXPORT_ROWS",
            "MAX_COLUMNS",
            "TrackerSpreadsheetError",
            "field_values",
            "text_value",
            "full_name",
            "normalized_name",
            "normalized_passport",
        ],
        spreadsheet_reader: ["_header", "_HEADERS", "_bounded_rows", "read_rows"],
        spreadsheet_matching: ["match_rows"],
        spreadsheet_export: ["_safe", "build_export"],
    }
    for owner, names in owners.items():
        for name in names:
            actual = getattr(spreadsheets, name)
            assert actual is getattr(owner, name)
            if inspect.isfunction(actual):
                assert get_type_hints(actual)


def test_service_runtime_annotations_private_query_seams_and_actor_defaults():
    assert service.TRACKER_ROLES is queries.TRACKER_ROLES
    constructor = inspect.signature(service.TravelTrackerService)
    assert constructor.parameters["allowed_group_ids"].default is None
    assert constructor.parameters["actor_already_fenced"].default is False
    assert constructor.parameters["actor_already_fenced"].kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(service.TravelTrackerService._group)["return"] is ClientGroupModel
    assert inspect.signature(service.TravelTrackerService.mark).parameters["commit"].default is True
    for name, method in vars(service.TravelTrackerService).items():
        if isinstance(method, staticmethod):
            method = method.__func__
        if inspect.isfunction(method):
            assert get_type_hints(method), name
