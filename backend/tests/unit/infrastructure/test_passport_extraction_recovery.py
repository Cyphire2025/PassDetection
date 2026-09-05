from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import BackgroundTasks
from sqlalchemy.dialects import postgresql

from app.infrastructure.processing import recovery
from app.infrastructure.processing.dispatcher import PassportProcessingDispatcher
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository


async def test_broker_and_priority_publication_run_outside_the_request_thread() -> None:
    request_thread = threading.get_ident()
    threads = []
    dispatcher = PassportProcessingDispatcher(backend="celery", priority_coordinator=Mock())
    dispatcher._send_celery = Mock(
        side_effect=lambda **_: (
            threads.append(threading.get_ident()),
            SimpleNamespace(id="queued-task"),
        )[1]
    )
    assert (
        await dispatcher.dispatch_async(
            job_id=uuid.uuid4(), submission_id=uuid.uuid4(), background_tasks=BackgroundTasks()
        )
        == "queued-task"
    )
    assert threads and all(thread != request_thread for thread in threads)


async def test_recovery_leases_stale_rows_before_publishing_and_respects_attempt_budget() -> None:
    now = datetime.now(tz=UTC)

    def job(attempts: int) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            submission_id=uuid.uuid4(),
            queue_name="passport_ocr",
            status="queued",
            attempts=attempts,
            max_attempts=3,
            extraction_revision=2,
            progress=0.0,
            current_stage="queued",
            error_message=None,
            celery_task_id="previous-published-message",
            cancel_requested=False,
            created_at=now - timedelta(minutes=5),
            updated_at=now - timedelta(minutes=5),
            started_at=None,
            finished_at=None,
        )

    stranded, exhausted = job(0), job(3)
    result = Mock()
    result.scalars.return_value = [stranded, exhausted]
    session = Mock(execute=AsyncMock(return_value=result), flush=AsyncMock())
    jobs = await PassportProcessingJobRepository(session).claim_recoverable_jobs(limit=2)
    assert [item.id for item in jobs] == [stranded.id]
    assert stranded.current_stage == "recovery_queued"
    assert stranded.updated_at >= now
    assert exhausted.status == "dead_letter"
    assert exhausted.attempts == 3
    statement = session.execute.call_args.args[0]
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "LIMIT 2" in sql
    assert "celery_task_id IS NULL" not in sql


async def test_autonomous_recovery_commits_lease_before_dispatch_without_any_http_request(
    monkeypatch,
) -> None:
    events = []
    job = SimpleNamespace(id=uuid.uuid4(), submission_id=uuid.uuid4())
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.commit.side_effect = lambda: events.append("commit")
    repository = Mock(claim_recoverable_jobs=AsyncMock(return_value=[job]), set_task_id=AsyncMock())
    monkeypatch.setattr(recovery, "AsyncSessionFactory", Mock(return_value=session))
    monkeypatch.setattr(recovery, "PassportProcessingJobRepository", Mock(return_value=repository))

    async def dispatch(**kwargs):
        events.append("dispatch")
        return "recovered-task"

    monkeypatch.setattr(
        recovery, "PassportProcessingDispatcher", Mock(return_value=Mock(dispatch_async=dispatch))
    )
    assert await recovery.recover_passport_extractions() == 1
    assert events == ["commit", "dispatch", "commit"]
    repository.set_task_id.assert_awaited_once_with(job.id, "recovered-task")
    await asyncio.gather(*tuple(recovery._LOCAL_RECOVERIES))


async def test_local_recovery_capacity_prevents_unbounded_outage_work(monkeypatch) -> None:
    session_factory = Mock()
    monkeypatch.setattr(recovery, "AsyncSessionFactory", session_factory)
    blocker = asyncio.Event()
    tasks = {asyncio.create_task(blocker.wait()) for _ in range(recovery.MAX_LOCAL_RECOVERIES)}
    monkeypatch.setattr(recovery, "_LOCAL_RECOVERIES", tasks)
    try:
        assert await recovery.recover_passport_extractions() == 0
        session_factory.assert_not_called()
    finally:
        blocker.set()
        await asyncio.gather(*tasks)
