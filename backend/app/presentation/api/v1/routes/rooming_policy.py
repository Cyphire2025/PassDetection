"""Office and coordinator role boundaries shared by rooming workflows."""

from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES, UserRole

ROOMING_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]
CHECKIN_ROLES = [*ROOMING_ROLES, UserRole.AGENCY_COORDINATOR]
ROOMING_PASSENGER_STATUSES = OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
