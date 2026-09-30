"""Neutral result shape shared by website and MCP administrative observations."""

from typing import TypedDict

ADMIN_OVERVIEW_FIELDS = (
    "agencies", "users", "client_groups", "passport_submissions",
    "pending_review", "client_submitted", "failed",
)


class AdminOverviewCounts(TypedDict):
    agencies: int
    users: int
    client_groups: int
    passport_submissions: int
    pending_review: int
    client_submitted: int
    failed: int
