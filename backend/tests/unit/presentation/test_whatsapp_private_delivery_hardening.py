"""Route contracts for private WhatsApp delivery hardening."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.infrastructure.database.models import (
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.presentation.api.v1.routes.tour_operations import (
    router as tour_operations_router,
)
from app.presentation.api.v1.routes.tour_operations_qr_delivery import (
    _matched_recipients,
)
from app.presentation.api.v1.routes.whatsapp import router as whatsapp_router

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


def test_main_authenticated_whatsapp_mutations_require_cookie_csrf() -> None:
    expected = {
        ("/groups/{group_id}/rejected-contacts/{rejected_contact_id}/resolve", "POST"),
        ("/groups/{group_id}/welcome-media", "POST"),
        ("/groups", "POST"),
        ("/groups/{group_id}", "PATCH"),
        ("/groups/{group_id}/recipients", "POST"),
        ("/groups/{group_id}/recipients/{recipient_id}", "PATCH"),
        ("/groups/{group_id}/recipients/{recipient_id}", "DELETE"),
        ("/groups/{group_id}/recipients/{recipient_id}/resend", "POST"),
        ("/groups/{group_id}", "DELETE"),
        ("/groups/{group_id}/send", "POST"),
    }

    for path, method in expected:
        route = next(
            route
            for route in whatsapp_router.routes
            if route.path == path and method in route.methods
        )
        dependencies = {dependency.call.__name__ for dependency in route.dependant.dependencies}
        assert "require_cookie_csrf" in dependencies, (path, method)

    for path in ("/webhook", "/contacts/preview", "/groups/{group_id}/preview"):
        route = next(route for route in whatsapp_router.routes if route.path == path)
        dependencies = {dependency.call.__name__ for dependency in route.dependant.dependencies}
        assert "require_cookie_csrf" not in dependencies


def test_attendance_qr_lifecycle_mutations_require_cookie_csrf() -> None:
    expected = {
        ("/groups/{group_id}/passengers/{passenger_id}/qr", "POST"),
        (
            "/groups/{group_id}/passengers/{passenger_id}/qr/regenerate",
            "POST",
        ),
        ("/groups/{group_id}/passengers/{passenger_id}/qr/revoke", "POST"),
        ("/groups/{group_id}/passengers/{passenger_id}/qr/active", "PATCH"),
        (
            "/groups/{group_id}/passengers/{passenger_id}/qr/expiration",
            "PATCH",
        ),
    }

    for path, method in expected:
        route = next(
            route
            for route in tour_operations_router.routes
            if route.path == path and method in route.methods
        )
        dependencies = {dependency.call.__name__ for dependency in route.dependant.dependencies}
        assert "require_cookie_csrf" in dependencies, (path, method)


def test_qr_private_delivery_never_selects_first_shared_phone_passenger() -> None:
    broadcast_id = uuid.uuid4()
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        broadcast_group_id=broadcast_id,
        name="Family contact",
        phone_number="+919876543210",
        normalized_phone_number="+919876543210",
        imported_fields={},
        created_at=NOW,
    )
    group_id = uuid.uuid4()
    passengers = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=recipient.agency_id,
            group_id=group_id,
            client_name=f"Passenger {index}",
            family_head_phone=recipient.normalized_phone_number,
            image_s3_key=f"private-test/{index}.jpg",
            status="confirmed",
            confirmed_fields={},
            extracted_fields={},
            staff_metadata={},
            created_at=NOW,
            updated_at=NOW,
        )
        for index in range(2)
    ]

    matched, ambiguous = _matched_recipients(
        submissions=passengers,
        recipients=[recipient],
        linked_broadcasts={broadcast_id: "Family"},
    )

    assert matched == {}
    assert ambiguous == {passenger.id for passenger in passengers}


def test_qr_private_delivery_rejects_configured_generic_answer_match() -> None:
    agency_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        broadcast_group_id=broadcast_id,
        name="Roster Name",
        phone_number="+919222222222",
        normalized_phone_number="+919222222222",
        imported_fields={"Producer Code": "PR-42"},
        created_at=NOW,
    )
    passenger = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=uuid.uuid4(),
        client_name="Submitted Name",
        client_phone="+919111111111",
        image_s3_key="private-test/configured.jpg",
        status="confirmed",
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
        custom_answers=[{"label": "Producer Code", "value": "PR-42"}],
        custom_detail_answers=[],
        created_at=NOW,
        updated_at=NOW,
    )

    matched, ambiguous = _matched_recipients(
        submissions=[passenger],
        recipients=[recipient],
        linked_broadcasts={broadcast_id: "Configured list"},
        matching_fields_by_broadcast={broadcast_id: ("producer_code",)},
    )

    assert ambiguous == set()
    assert matched == {}


def test_qr_private_delivery_accepts_configured_phone_match() -> None:
    agency_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        broadcast_group_id=broadcast_id,
        name="Roster Name",
        phone_number="+919222222222",
        normalized_phone_number="+919222222222",
        imported_fields={"Mobile": "+919222222222"},
        created_at=NOW,
    )
    passenger = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=uuid.uuid4(),
        client_name="Submitted Name",
        client_phone="+919222222222",
        image_s3_key="private-test/configured-phone.jpg",
        status="confirmed",
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
        created_at=NOW,
        updated_at=NOW,
    )

    matched, ambiguous = _matched_recipients(
        submissions=[passenger],
        recipients=[recipient],
        linked_broadcasts={broadcast_id: "Configured list"},
        matching_fields_by_broadcast={broadcast_id: ("phone_number",)},
    )

    assert ambiguous == set()
    assert matched == {passenger.id: (recipient, "Configured list")}
