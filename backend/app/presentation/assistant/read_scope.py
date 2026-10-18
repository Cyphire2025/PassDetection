"""Granting the assistant never expands a lower-role dashboard data boundary."""

from app.domain.entities.entities import User, UserRole

# These reviewed readers already support office principals and enforce canonical
# group visibility. Platform administration, credentials, raw history and provider
# operations stay unavailable to delegated assistant users.
OFFICE_VIEWS = frozenset(
    {
        "group_links",
        "group_details",
        "passport_details",
        "passport_client_details",
        "passport_view",
        "document_groups",
        "document_review",
        "document_delivery_summary",
        "rooming_workspace",
        "rooming_priority_fields",
        "rooming_field_values",
        "menu_workspace",
        "tour_groups",
        "tour_passengers",
        "personal_notifications",
        "global_search",
        "dashboard_summary",
    }
)


def view_allowed(user: User | None, view: str) -> bool:
    return user is None or user.role == UserRole.SUPER_ADMIN or view in OFFICE_VIEWS
