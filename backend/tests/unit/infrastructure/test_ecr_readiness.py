from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import AgencyModel
from app.infrastructure.ecr.readiness import ecr_backlog, ecr_capability


async def test_ecr_backlog_measures_durable_pending_retry_and_failure(db_session):
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic health", email="health@example.test")
    db_session.add(agency)
    await db_session.flush()
    batch = EcrBatchModel(id=uuid.uuid4(), agency_id=agency.id, title="Synthetic health", expected_count=5)
    db_session.add(batch)
    await db_session.flush()
    now = datetime.now(UTC)
    for state, attempts in (("queued", 0), ("queued", 1), ("processing", 1), ("processing", 2), ("failed", 3)):
        db_session.add(EcrItemModel(
            id=uuid.uuid4(), batch_id=batch.id, client_id=uuid.uuid4(),
            original_filename="synthetic.jpg", content_type="image/jpeg", sha256="0" * 64,
            status=state, attempts=attempts, created_at=now - timedelta(minutes=20),
        ))
    await db_session.flush()
    backlog = await ecr_backlog(db_session)
    assert backlog is not None
    assert backlog["pending_count"] == 4
    assert backlog["retry_count"] == 2  # first active attempts are not retries
    assert backlog["failed_count"] == 1
    assert backlog["oldest_pending_seconds"] >= 1200
    capability = ecr_capability(("available", True), backlog)
    assert capability["status"] == "backlog_over_15m"
    assert capability["traffic_gate"] is False
    assert capability["available"] is False


async def test_missing_optional_ledger_keeps_outer_transaction_usable(db_session):
    await db_session.execute(text("DROP TABLE ecr_items"))
    assert await ecr_backlog(db_session) is None
    assert await db_session.scalar(text("SELECT 1")) == 1
    assert ecr_capability(("available", True), None)["status"] == "backlog_probe_failed"


def test_stopped_worker_is_not_reported_available_when_queue_is_empty():
    backlog = {"pending_count": 0, "retry_count": 0, "failed_count": 0, "oldest_pending_seconds": 0}
    capability = ecr_capability(("no_consumer", False), backlog)
    assert capability["available"] is False
    assert capability["traffic_gate"] is False
    assert capability["worker_available"] is False
    assert capability["status"] == "no_consumer"
    assert ecr_capability(("available", True), backlog)["available"] is True
