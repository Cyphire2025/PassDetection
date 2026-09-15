"""Reserved metadata proving completion through the public collection workflow."""

from collections.abc import Mapping

CLIENT_COLLECTION_SUBMITTED_KEY = "client_collection_submitted"
CLIENT_COLLECTION_SUBMITTED_VALUE = "public_group_link_v1"


def mark_client_collection_submitted(metadata: Mapping[str, str] | None) -> dict[str, str]:
    return {**(metadata or {}), CLIENT_COLLECTION_SUBMITTED_KEY: CLIENT_COLLECTION_SUBMITTED_VALUE}


def strip_client_collection_provenance(metadata: Mapping[str, str] | None) -> dict[str, str]:
    """Imported metadata cannot supply the server-owned public completion marker."""
    return {
        key: value
        for key, value in (metadata or {}).items()
        if key != CLIENT_COLLECTION_SUBMITTED_KEY
    }
