"""Read bounded resource observations from the isolated QA stack."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.config.settings import get_settings
from app.infrastructure.database.ecr_models import EcrBatchModel
from app.infrastructure.database.session import AsyncSessionFactory
from sqlalchemy import func, select, text


async def observe(run_id: str, seconds: int) -> None:
    from redis.asyncio import Redis

    settings = get_settings()
    # Bound awaited I/O, not only the clock check between completed samples.
    async with asyncio.timeout(seconds + 10):
        async with Redis.from_url(
            settings.redis.broker_url, socket_connect_timeout=5, socket_timeout=5
        ) as redis:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                async with AsyncSessionFactory() as db:
                    connections = (
                        await db.execute(
                            text(
                                "SELECT state, wait_event_type, count(*) FROM pg_stat_activity "
                                "GROUP BY state, wait_event_type"
                            )
                        )
                    ).all()
                    pending, oldest = (
                        await db.execute(
                            select(func.count(), func.min(EcrBatchModel.created_at)).where(
                                EcrBatchModel.title == f"capacity-{run_id}",
                                EcrBatchModel.status.in_(["queued", "processing"]),
                            )
                        )
                    ).one()
                    maximum = int(await db.scalar(text("SHOW max_connections")))
                memory_file = Path("/sys/fs/cgroup/memory.current")
                queues = {
                    name: int(await redis.llen(name)) for name in ("passport_ocr", "ecr_checks")
                }
                print(
                    json.dumps(
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "database_connections": sum(row[2] for row in connections),
                            "database_active": sum(
                                row[2] for row in connections if row[0] == "active"
                            ),
                            "database_lock_waiters": sum(
                                row[2] for row in connections if row[1] == "Lock"
                            ),
                            "database_max_connections": maximum,
                            "queues": queues,
                            "pending_durable_jobs": pending,
                            "oldest_pending_age_seconds": (
                                datetime.now(UTC) - oldest
                            ).total_seconds()
                            if oldest
                            else 0,
                            "backend_cgroup_memory_bytes": int(memory_file.read_text()),
                            "backend_memory_events": {
                                name: int(value)
                                for name, value in (
                                    line.split()
                                    for line in Path("/sys/fs/cgroup/memory.events")
                                    .read_text()
                                    .splitlines()
                                )
                            },
                        }
                    ),
                    flush=True,
                )
                await asyncio.sleep(2)


# Preserve the original function identity through capacity_fixtures.
for _export in (observe,):
    _export.__module__ = "capacity_fixtures"
del _export
