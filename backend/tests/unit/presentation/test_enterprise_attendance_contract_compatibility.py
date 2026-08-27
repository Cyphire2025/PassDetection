from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.core.config.settings import Settings
from app.main import create_application
from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutCheckpointRequest,
)
from app.presentation.api.v1.schemas.attendance_runtime_schemas import (
    AttendanceDiscardBatchRequest,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceMissingPassengersPageResponse,
    AttendanceScanRequest,
    AttendanceSessionResponse,
    GroupAttendanceSummaryResponse,
)


def test_old_clients_can_continue_publishing_account_scoped_closeout() -> None:
    legacy_payload = {
        "pending_count": 0,
        "sending_count": 0,
        "retryable_count": 0,
        "needs_review_count": 0,
        "unreviewed_rejected_count": 0,
        "oldest_pending_age_seconds": None,
    }

    parsed = AttendanceCloseoutCheckpointRequest.model_validate(legacy_payload)

    assert parsed.runtime_id is None
    assert parsed.model_dump(exclude_none=True) == {
        key: value for key, value in legacy_payload.items() if value is not None
    }


def test_old_attendance_session_responses_gain_schedule_fields_additively() -> None:
    legacy_response = {
        "id": str(uuid.uuid4()),
        "group_id": str(uuid.uuid4()),
        "name": "Airport reporting",
        "status": "active",
        "created_at": "2026-08-23T08:00:00Z",
        "started_at": "2026-08-23T08:01:00Z",
        "completed_at": None,
        "scanned_count": 10,
        "assigned_count": 20,
    }

    parsed = AttendanceSessionResponse.model_validate(legacy_response)

    assert parsed.scheduled_starts_at is None
    assert parsed.scheduled_ends_at is None
    assert parsed.schedule_timezone is None
    assert parsed.schedule_version == 1
    assert parsed.scanned_count == 10
    assert parsed.assigned_count == 20


def test_existing_scan_request_contract_remains_stable() -> None:
    request = AttendanceScanRequest(
        qr_payload=f"pdatt:{'a' * 43}",
        client_event_id="existing-client-event-0001",
        scanned_at=datetime(2026, 8, 23, 8, 5, tzinfo=UTC),
        device_id="existing-installation-01",
        sync_source="offline",
    )

    assert set(request.model_dump()) == {
        "qr_payload",
        "client_event_id",
        "scanned_at",
        "device_id",
        "sync_source",
        "runtime_id",
    }
    assert request.runtime_id is None


def test_new_summary_and_missing_page_schemas_are_pii_bounded() -> None:
    schema_text = json.dumps(
        {
            "summary": GroupAttendanceSummaryResponse.model_json_schema(),
            "missing": AttendanceMissingPassengersPageResponse.model_json_schema(),
        },
        sort_keys=True,
    ).lower()

    for forbidden in (
        "client_email",
        "client_phone",
        "passport_number",
        "family_group",
        "departure_city",
        "qr_payload",
    ):
        assert forbidden not in schema_text
    assert "display_name" in schema_text
    assert "next_cursor" in schema_text
    assert "revision" in schema_text


def test_openapi_exposes_additive_enterprise_attendance_routes() -> None:
    application = create_application(
        settings=Settings(
            app_env="development",
            app_secret_key="attendance-contract-test-not-production",
            app_debug=False,
            login_lockout_require_redis=False,
            dashboard_rate_limit_require_redis=False,
            public_upload_rate_limit_require_redis=False,
            _env_file=None,
        ),
        initialize_rate_limit_redis=False,
    )
    openapi = application.openapi()
    paths = openapi["paths"]

    assert "/api/v1/tour-operations/groups/{group_id}/attendance/summary" in paths
    assert (
        "/api/v1/tour-operations/groups/{group_id}/attendance/sessions/"
        "{session_id}/missing" in paths
    )
    assert "/api/v1/tour-operations/coordinator/attendance/runtime" in paths
    assert "/api/v1/tour-operations/coordinator/attendance/discards" in paths
    assert "get" in paths["/api/v1/tour-operations/groups/{group_id}/attendance/summary"]
    assert "post" in paths["/api/v1/tour-operations/coordinator/attendance/discards"]


def test_discard_batch_body_keeps_runtime_hint_optional_for_transition_clients() -> None:
    item = {
        "discard_event_id": str(uuid.uuid4()),
        "group_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "scan_reference": f"sha256:{'b' * 64}",
        "reason_category": "server_terminal_rejection",
        "captured_at": "2026-08-23T08:00:00Z",
        "discarded_at": "2026-08-23T08:01:00Z",
    }

    parsed = AttendanceDiscardBatchRequest.model_validate({"items": [item]})

    assert parsed.runtime_id is None
    assert parsed.items[0].installation_runtime_id is None
    assert parsed.items[0].scan_reference == "b" * 64
