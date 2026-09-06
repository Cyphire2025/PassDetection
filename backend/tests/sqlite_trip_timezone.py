"""Test-only PostgreSQL timezone(tz, timestamptz) equivalent for SQLite."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


async def register_sqlite_trip_timezone(session: AsyncSession) -> None:
    def timezone(name: str, value: str) -> str:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        # PostgreSQL timezone returns local wall time WITHOUT a timezone.
        return timestamp.astimezone(ZoneInfo(name)).replace(tzinfo=None).isoformat(" ")

    def register(sync_session: Session) -> None:
        sync_session.connection().connection.dbapi_connection.create_function(
            "timezone", 2, timezone
        )

    await session.run_sync(register)
