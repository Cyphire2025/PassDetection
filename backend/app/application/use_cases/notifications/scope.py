"""Canonical current-user scope for the website's personal notification feed."""

from uuid import UUID

from app.domain.entities.entities import User, UserRole


def direct_notification_agency(user: User) -> UUID | None:
    # Superadmins see their own direct notifications across agencies. This is
    # still recipient-bound, including accounts without an assigned agency.
    return None if user.role == UserRole.SUPER_ADMIN else user.agency_id
