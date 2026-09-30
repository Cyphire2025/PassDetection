"""Canonical rename read scope and recorded download eligibility, without I/O."""

from uuid import UUID

from app.domain.entities.entities import User, UserRole
from app.domain.value_objects.travel_document_taxonomy import SUPPORTED_TRAVEL_DOCUMENT_TYPES


class DocumentRenameScopeError(PermissionError):
    pass


def rename_agency(user: User) -> UUID:
    if not user.agency_id or user.role == UserRole.AGENCY_COORDINATOR:
        raise DocumentRenameScopeError("Insufficient permissions")
    return user.agency_id


def download_metadata_eligible(detected_type: str, status: str, storage_present: bool) -> bool:
    """Recorded metadata permits the website link; storage existence is unverified."""
    return detected_type in SUPPORTED_TRAVEL_DOCUMENT_TYPES and status != "rejected" and storage_present
