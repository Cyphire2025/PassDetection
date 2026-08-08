"""Shared SQLAlchemy registry and column primitives."""

from datetime import UTC, datetime

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB as PostgreSQLJSONB
from sqlalchemy.orm import DeclarativeBase

JSONB = JSON().with_variant(PostgreSQLJSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass
