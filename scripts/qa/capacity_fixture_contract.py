"""Fixed synthetic dataset sizes and deterministic run-scoped identifiers."""

from __future__ import annotations

import uuid

TENANTS = 10

SMALL_GROUP = 100

LARGE_GROUP = 5000


def identifier(run_id: str, name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.UUID(run_id), name)


identifier.__module__ = "capacity_fixtures"
