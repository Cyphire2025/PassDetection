"""Compatibility projection for the append-only mobile sync journal."""

from typing import Literal

from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.infrastructure.database.gc_mobile_models import MobileSyncChangeModel

MobileSyncOperation = Literal["upsert", "delete", "revoke"]


def mobile_sync_operation(value: str, *, entity_type: str = "") -> MobileSyncOperation:
    # Old clients treat any revoke as trip access loss. Normalize historical
    # content withdrawals on read without rewriting journal IDs or sequences.
    if value == "revoke" and entity_type in {"announcement", "itinerary", "common_document"}:
        return "delete"
    if value in {"upsert", "publish"}:
        return "upsert"
    if value == "delete":
        return "delete"
    if value == "revoke":
        return "revoke"
    raise ValueError("Unsupported mobile sync operation")


def authorized_mobile_sync_operation(
    change: MobileSyncChangeModel, trip: AuthorizedMobileTrip,
) -> MobileSyncOperation:
    """Project old access invalidations against the reader's current authority.

    Call only after the active device/session dependency and require_trip_access
    succeed. Window edits revoke old sessions but historically wrote role
    revokes into the *new* group generation. Reauthenticated readers must not
    replay that old session's loss of access. The same applies to an identity
    revoked and subsequently re-authorized under a new claim generation.

    Genuine current removals fail authorization before reaching this projection.
    Exact journal/authority matching keeps unrelated or unknown removals intact;
    no row, sequence, event identity, or cursor is rewritten.
    """
    operation = mobile_sync_operation(change.operation, entity_type=change.entity_type)
    if operation != "revoke" or (
        change.agency_id != trip.access.agency_id
        or change.gc_group_access_id != trip.access.id
        or change.group_id != trip.group.id
        or change.access_generation != trip.access.access_generation
        or change.audience not in {"all", trip.principal_type}
    ):
        return operation
    if change.entity_type in {"group_access", "gc_group_access"}:
        return "upsert" if change.entity_id == trip.access.id else operation
    if change.entity_type == "role_access":
        if change.entity_id == trip.access.id and change.audience == trip.principal_type:
            return "upsert"
    if change.entity_type == "passenger_identity":
        identity = trip.passenger_identity
        if (
            trip.principal_type == "passenger"
            and identity is not None
            and change.entity_id == identity.id
            and change.passenger_identity_id == identity.id
        ):
            return "upsert"
    return operation
