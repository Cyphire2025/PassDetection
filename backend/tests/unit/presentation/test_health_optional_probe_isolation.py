"""Real health orchestration over explicit PostgreSQL-shaped transaction states.

No PostgreSQL connection is opened. The fixture models statement failure and
savepoint rollback only; it is not native-driver/server qualification.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.config.release_contract import SCHEMA_REVISION
from app.core.config.settings import Settings
from app.infrastructure import runtime_readiness
from app.infrastructure.readiness_executor import ReadinessProbeExecutor
from app.infrastructure.runtime_readiness_database import _cleanup_backlog
from app.presentation.api.v1.routes import health


class PostgreSQLShapedSession:
    """A failed statement blocks later SQL until rollback to its savepoint."""

    def __init__(self, *, fail_cleanup=False, cancel_cleanup=False):
        self.fail_cleanup = fail_cleanup
        self.cancel_cleanup = cancel_cleanup
        self.aborted = False
        self.savepoint_rollbacks = 0
        self.outer_rollbacks = 0
        self.pending_outer_changes = ["synthetic-unrelated-request-change"]
        self.cleanup_started = asyncio.Event()
        self.statements = []

    @asynccontextmanager
    async def begin_nested(self):
        if self.aborted:
            raise self._failure("SAVEPOINT", "current transaction is aborted")
        preserved = list(self.pending_outer_changes)
        try:
            yield
        except BaseException:
            self.aborted = False
            self.pending_outer_changes = preserved
            self.savepoint_rollbacks += 1
            raise

    async def rollback(self):
        self.outer_rollbacks += 1
        self.pending_outer_changes.clear()
        self.aborted = False

    @staticmethod
    def _failure(statement, message):
        return DBAPIError(statement, None, RuntimeError(message))

    async def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if self.aborted:
            raise self._failure(sql, "current transaction is aborted")
        if "alembic_version" in sql:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [SCHEMA_REVISION]))
        if "storage_cleanup_jobs" in sql:
            self.cleanup_started.set()
            if self.cancel_cleanup:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.aborted = True
                    raise
            if self.fail_cleanup:
                self.aborted = True
                raise self._failure(sql, "synthetic-private-cleanup-query-diagnostic")
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    one=lambda: {
                        "due_count": 0,
                        "blocked_count": 0,
                        "oldest_due_seconds": 0,
                    }
                )
            )
        if "ecr_items" in sql or "passport_ecr_checks" in sql:
            return SimpleNamespace(one=lambda: (0, 0, 0, None))
        return SimpleNamespace()


@pytest.fixture
def normal_health_dependencies(monkeypatch):
    executor = ReadinessProbeExecutor()
    monkeypatch.setattr(health, "readiness_probe_executor", executor)
    monkeypatch.setattr(
        health, "get_ai_priority_coordinator", lambda: SimpleNamespace(snapshot=lambda: None)
    )
    monkeypatch.setattr(health, "gemini_worker_readiness", lambda _: ({}, True))
    monkeypatch.setattr(health, "email_runtime_readiness", lambda _: ({}, True))
    monkeypatch.setattr(health, "gemini_configuration_readiness", lambda _: ({}, True))
    monkeypatch.setattr(
        health,
        "get_mobile_realtime_hub",
        lambda: SimpleNamespace(readiness=lambda: ("disabled", True)),
    )
    blocking = runtime_readiness._BlockingSnapshot(
        checks={
            "security_redis": "not_required",
            "object_storage": "available",
            "malware_scanner": "not_required_ingestion_disabled",
            "general_processing_worker": "available",
            "platform_scheduler": "heartbeat_recent",
            "my_photos": "not_required_feature_disabled",
            "ecr_worker": "available",
        },
        security_ready=True,
        object_storage_ready=True,
        malware_ready=True,
        general_worker_ready=True,
        scheduler_ready=True,
        my_photos_ready=True,
        my_photos_required=False,
        ecr_worker=("available", True),
    )
    monkeypatch.setattr(
        runtime_readiness.RuntimeReadinessProbe,
        "_blocking_snapshot",
        AsyncMock(return_value=blocking),
    )
    monkeypatch.setattr(
        runtime_readiness, "_runtime_probe", runtime_readiness.RuntimeReadinessProbe()
    )
    try:
        yield Settings(app_secret_key="synthetic-optional-probe-isolation", _env_file=None)
    finally:
        executor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_cleanup", [False, True])
async def test_optional_cleanup_failure_cannot_degrade_independent_ecr_readiness(
    normal_health_dependencies,
    fail_cleanup,
):
    db = PostgreSQLShapedSession(fail_cleanup=fail_cleanup)
    response = await health.readiness(db=db, settings=normal_health_dependencies)
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["capabilities"]["storage_cleanup"]["available"] is not fail_cleanup
    assert body["capabilities"]["storage_cleanup"]["traffic_gate"] is False
    assert body["capabilities"]["ecr_checks"]["available"] is True
    assert body["capabilities"]["ecr_checks"]["backlog"]["pending_count"] == 0
    assert "synthetic-private-cleanup-query-diagnostic" not in response.body.decode()
    assert not db.aborted and db.outer_rollbacks == 0
    assert db.pending_outer_changes == ["synthetic-unrelated-request-change"]
    await db.execute("SELECT 1")


@pytest.mark.asyncio
async def test_cleanup_error_rolls_back_only_its_own_optional_work():
    db = PostgreSQLShapedSession(fail_cleanup=True)
    backlog = await _cleanup_backlog(db)
    assert backlog.blocked_count == 1
    assert not db.aborted and db.savepoint_rollbacks == 1 and db.outer_rollbacks == 0
    assert db.pending_outer_changes == ["synthetic-unrelated-request-change"]
    await db.execute("SELECT 1")


@pytest.mark.asyncio
async def test_cleanup_cancellation_propagates_and_releases_its_savepoint():
    db = PostgreSQLShapedSession(cancel_cleanup=True)
    task = asyncio.create_task(_cleanup_backlog(db))
    await db.cleanup_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not db.aborted and db.savepoint_rollbacks == 1 and db.outer_rollbacks == 0
    assert db.pending_outer_changes == ["synthetic-unrelated-request-change"]
