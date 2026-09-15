"""Compatibility projection for the append-only mobile sync journal."""

from typing import Literal

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
