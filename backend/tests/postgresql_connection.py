"""Construct isolated service-test connection addresses without URL interpolation."""

from __future__ import annotations

import os

from sqlalchemy import URL


def service_test_url() -> URL:
    """Keep credentials and IPv6 hosts as fields for the driver's URL parser."""
    return URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
    )
