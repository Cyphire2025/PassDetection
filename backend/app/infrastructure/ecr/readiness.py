"""Optional ECR capability health, independent of admission for other features."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.ecr_models import EcrItemModel
from app.infrastructure.database.passport_ecr_models import PassportEcrCheckModel
from app.infrastructure.observability.metrics import metrics

BACKLOG_WARNING_SECONDS = 15 * 60


async def ecr_backlog(db: AsyncSession) -> dict[str, int] | None:
    """Aggregate both durable ledgers; no payloads, identifiers or full-row loads."""
    queued = failed = retries = oldest_seconds = 0
    now = datetime.now(UTC)
    try:
        # Roll back only optional probe work if a table is temporarily missing.
        # Leaving PostgreSQL's outer transaction aborted would turn a non-gating
        # capability failure into a failing dependency/session commit.
        async with db.begin_nested():
            for model in (EcrItemModel, PassportEcrCheckModel):
                pending = model.status.in_(("queued", "processing"))
                retrying = or_(
                    (model.status == "queued") & (model.attempts > 0),
                    (model.status == "processing") & (model.attempts > 1),
                )
                row = (await db.execute(select(
                    func.count().filter(pending),
                    func.count().filter(model.status == "failed"),
                    func.count().filter(retrying),
                    func.min(model.created_at).filter(pending),
                ).where(model.status.in_(("queued", "processing", "failed"))))).one()
                queued += int(row[0])
                failed += int(row[1])
                retries += int(row[2])
                if row[3] is not None:
                    oldest = row[3]
                    if oldest.tzinfo is None:
                        oldest = oldest.replace(tzinfo=UTC)
                    oldest_seconds = max(oldest_seconds, int((now - oldest).total_seconds()))
    except Exception:
        # Optional diagnostic queries must never claim a healthy empty queue on
        # a missing table, schema mismatch, or database failure.
        metrics.set_gauge("ecr.backlog_probe_available", 0)
        return None
    result = {
        "pending_count": queued,
        "failed_count": failed,
        "retry_count": retries,
        "oldest_pending_seconds": max(0, oldest_seconds),
    }
    metrics.set_gauge("ecr.backlog_probe_available", 1)
    for name, value in result.items():
        metrics.set_gauge(f"ecr.{name}", value)
    return result


def ecr_capability(worker: tuple[str, bool], backlog: dict[str, int] | None) -> dict[str, object]:
    worker_status, worker_ready = worker
    metrics.set_gauge("ecr.worker_available", int(worker_ready))
    if not worker_ready:
        status = worker_status
    elif backlog is None:
        status = "backlog_probe_failed"
    elif backlog["oldest_pending_seconds"] > BACKLOG_WARNING_SECONDS:
        status = "backlog_over_15m"
    else:
        status = "available"
    return {
        "required": True,
        "available": status == "available",
        "traffic_gate": False,
        "status": status,
        "worker_available": worker_ready,
        "backlog": backlog,
    }
