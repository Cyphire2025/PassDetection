from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.security.mobile_jwt import MobileAccessClaims
from app.presentation.api.v1.routes import mobile_ops
from app.presentation.api.v1.routes import mobile_ops_notification_support as notification_support
from app.presentation.api.v1.routes import mobile_ops_passenger_support as passenger_support


def _claims(role: str) -> MobileAccessClaims:
    principal_id = uuid.uuid4()
    return MobileAccessClaims(
        principal_id=principal_id,
        account_id=principal_id,
        principal_type=role,  # type: ignore[arg-type]
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC),
    )


def test_mobile_ops_keeps_existing_support_import_seams() -> None:
    assert mobile_ops._accessible_group_ids is notification_support._accessible_group_ids
    assert mobile_ops._safe_public_payload is notification_support._safe_public_payload
    assert (
        mobile_ops._coordinator_document_category
        is passenger_support._coordinator_document_category
    )
    assert mobile_ops._safe_optional_date is passenger_support._safe_optional_date
    assert (
        mobile_ops._validate_manager_document_signature
        is passenger_support._validate_manager_document_signature
    )


def test_announcement_visibility_filter_remains_agency_and_publication_scoped() -> None:
    agency_id = uuid.uuid4()
    expression = notification_support._published_announcement_notification_filter(agency_id)
    sql = str(expression.compile(compile_kwargs={"literal_binds": True}))

    assert "gc_announcements.agency_id" in sql
    assert agency_id.hex in sql
    assert "gc_announcements.status = 'published'" in sql
    assert "gc_announcements.group_id = mobile_notifications.group_id" in sql
    assert "gc_announcements.gc_group_access_id = mobile_notifications.gc_group_access_id" in sql


def test_notification_response_preserves_shape_and_strips_private_payload_values() -> None:
    now = datetime.now(tz=UTC)
    notification_id = uuid.uuid4()
    trip_id = uuid.uuid4()
    response = notification_support._notification_response(
        SimpleNamespace(
            id=notification_id,
            group_id=trip_id,
            notification_type="document_ready",
            category="documents",
            priority="high",
            title="Document ready",
            body="Your document is ready.",
            deep_link_path="/documents",
            public_payload={
                "screen": "documents",
                "group_id": str(trip_id),
                "storage_key": "private/passport.pdf",
                "passport_number": "P1234567",
            },
            available_at=now,
            expires_at=None,
            read_at=None,
        )
    )

    assert response.id == notification_id
    assert response.trip_id == trip_id
    assert response.priority == "important"
    assert response.payload == {"screen": "documents", "group_id": str(trip_id)}


def test_coordinator_operational_projection_remains_bounded_and_fail_closed() -> None:
    staff_metadata: dict[object, object] = {
        "passport_number": "P1234567",
        "storage_key": "private/passport.pdf",
    }
    staff_metadata.update({f"safe_field_{index}": index for index in range(305)})

    details = passenger_support._coordinator_operational_details(
        staff_metadata=staff_metadata,
        custom_answers=[],
        custom_detail_answers=[],
    )

    assert len(details) == passenger_support._MAX_COORDINATOR_OPERATIONAL_DETAILS
    assert all("passport" not in item.key for item in details)
    assert all("storage" not in item.key for item in details)
    assert details[0].value == "0"
