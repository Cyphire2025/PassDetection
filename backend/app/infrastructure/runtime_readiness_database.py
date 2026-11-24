"""Read-only authoritative schema and storage-cleanup backlog checks."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.runtime_readiness_contracts import _CleanupBacklog


async def _schema_readiness(
    db: AsyncSession,
    settings: Settings,
) -> tuple[str, bool]:
    try:
        result = await db.execute(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
        versions = tuple(str(value) for value in result.scalars().all())
    except Exception:
        return "unavailable", False
    expected = settings.expected_database_schema_revision
    if versions == (expected,):
        return "compatible", True
    if not versions:
        return "missing", False
    if len(versions) > 1:
        return "multiple_heads", False
    return "revision_mismatch", False


async def _cleanup_backlog(db: AsyncSession) -> _CleanupBacklog:
    try:
        # Keep optional diagnostics from aborting the caller transaction.
        async with db.begin_nested():
            result = await db.execute(
                text(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE status IN ('pending', 'running')
                              AND next_attempt_at <= CURRENT_TIMESTAMP
                        ) AS due_count,
                        COUNT(*) FILTER (WHERE status = 'blocked') AS blocked_count,
                        COALESCE(
                            EXTRACT(EPOCH FROM (
                                CURRENT_TIMESTAMP - MIN(created_at) FILTER (
                                    WHERE status IN ('pending', 'running')
                                      AND next_attempt_at <= CURRENT_TIMESTAMP
                                )
                            )),
                            0
                        ) AS oldest_due_seconds
                    FROM storage_cleanup_jobs
                    """
                )
            )
            row = result.mappings().one()
            return _CleanupBacklog(
                due_count=max(0, int(row["due_count"] or 0)),
                blocked_count=max(0, int(row["blocked_count"] or 0)),
                oldest_due_seconds=max(0, int(row["oldest_due_seconds"] or 0)),
            )
    except Exception:
        # A missing/unreadable cleanup table is itself visible degradation. It
        # is not a second traffic gate because schema readiness already fails
        # closed for incompatible deployments.
        return _CleanupBacklog(
            due_count=0,
            blocked_count=1,
            oldest_due_seconds=0,
        )
