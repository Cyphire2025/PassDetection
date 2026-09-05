"""The lifecycle boundary shared by every public passport capability.

Retention is an office policy, not an extension of a traveller's bearer link.
Closed, archived and deleted groups grant no public access or retry grace.
"""

from app.domain.entities.entities import ClientGroup
from app.domain.exceptions.exceptions import EntityNotFoundError


def public_upload_is_active(group: ClientGroup | None) -> bool:
    return bool(group is not None and group.is_active() and group.deleted_at is None)


def require_active_public_upload(group: ClientGroup | None) -> ClientGroup:
    if group is None or not public_upload_is_active(group):
        raise EntityNotFoundError("ClientGroup", "upload link")
    return group
