"""Old imports remain exact aliases and relocated annotations resolve at runtime."""

import importlib
import inspect
from dataclasses import is_dataclass
from typing import get_type_hints

_ORIGINAL_IMPORTS = {
    "authored_notification_access": {
        "authored_notification_grants": [
            "AuthoredRecipientKey",
            "current_authored_grants",
            "retain_authorized_authored_notifications",
        ],
        "authored_notification_registrations": [
            "registrations_for_grants",
            "_session_bindings",
            "_device_grants",
        ],
        "authored_notification_targets": [
            "authored_notification_recipient_key",
            "load_authored_recipient_registrations",
            "_exclude_rotated_installation_attempts",
        ],
    },
    "authored_notification_service": {
        "authored_notification_drafts": [
            "require_draft",
            "_selected_labels",
            "draft_response",
            "save_notification_draft",
            "delete_notification_draft",
        ],
        "authored_notification_reviews": ["_audience", "preview_notification"],
        "authored_notification_send": ["batch_by_request", "send_notification", "_enqueue_batch"],
    },
    "notification_service": {
        "notification_announcements": [
            "enqueue_announcement_notifications",
            "cancel_announcement_notifications",
            "_enqueue_recipient_pages",
            "_announcement_notification",
            "_announcement_dedupe_key",
        ],
        "notification_authority": ["_retain_currently_authorized_notifications"],
        "notification_contracts": [
            "AnnouncementNotificationCounts",
            "DocumentChangeNotificationCounts",
            "CountdownNotificationCounts",
            "_RECIPIENT_PAGE_SIZE",
            "_COUNTDOWN_CLEANUP_PAGE_SIZE",
            "_NOTIFICATION_TYPE",
            "_COUNTDOWN_NOTIFICATION_TYPE",
            "_LOCK_SCREEN_TITLE",
            "_COUNTDOWN_DAYS",
            "_COUNTDOWN_TEMPLATES",
        ],
        "notification_countdown_recipients": [
            "_enqueue_countdown_recipients",
            "_enqueue_countdown_pages",
            "_insert_notifications_ignore_duplicates",
        ],
        "notification_countdown_schedule": [
            "schedule_trip_countdown_notifications",
            "_cancel_stale_countdowns",
        ],
        "notification_countdown_values": ["_countdown_notification_values"],
        "notification_delivery_states": [
            "_retry_delivery",
            "_fail_delivery",
            "_revoke_registration",
            "_refresh_notification_delivery_states",
            "_bounded_backoff_seconds",
            "_aware_utc",
        ],
        "notification_dispatch": ["dispatch_mobile_push_batch"],
        "notification_document_changes": [
            "enqueue_personal_document_change_notifications",
            "_enqueue_document_change_user_pages",
            "_enqueue_document_change_ids",
            "_personal_document_change_notification",
            "_document_change_dedupe_key",
        ],
        "notification_receipts": ["reconcile_mobile_push_receipts"],
        "notification_registrations": [
            "_load_recipient_registrations",
            "_notification_recipient_key",
        ],
    },
}


def test_original_notification_imports_are_actual_implementation_objects():
    for facade_name, groups in _ORIGINAL_IMPORTS.items():
        facade = importlib.import_module(f"app.application.mobile.{facade_name}")
        for owner_name, names in groups.items():
            owner = importlib.import_module(f"app.application.mobile.{owner_name}")
            for name in names:
                assert getattr(facade, name) is getattr(owner, name), (facade_name, name)

    facade = importlib.import_module("app.application.mobile.notification_service")
    assert facade.__all__ == [
        "AnnouncementNotificationCounts",
        "CountdownNotificationCounts",
        "DocumentChangeNotificationCounts",
        "cancel_announcement_notifications",
        "dispatch_mobile_push_batch",
        "enqueue_announcement_notifications",
        "enqueue_personal_document_change_notifications",
        "reconcile_mobile_push_receipts",
        "schedule_trip_countdown_notifications",
    ]


def test_relocated_annotations_resolve_for_real_functions_and_count_contracts():
    for facade_name, groups in _ORIGINAL_IMPORTS.items():
        facade = importlib.import_module(f"app.application.mobile.{facade_name}")
        for names in groups.values():
            for name in names:
                value = getattr(facade, name)
                if inspect.isfunction(value) or (inspect.isclass(value) and is_dataclass(value)):
                    assert get_type_hints(value), (facade_name, name)

    for owner_name, name in (
        ("notification_dispatch_claims", "claim_due_push_notifications"),
        ("notification_dispatch_targets", "prepare_push_targets"),
        ("notification_dispatch_targets", "PushDispatchTargets"),
        ("notification_dispatch_results", "apply_push_tickets"),
    ):
        owner = importlib.import_module(f"app.application.mobile.{owner_name}")
        assert get_type_hints(getattr(owner, name)), name
