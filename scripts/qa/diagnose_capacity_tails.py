"""Bounded timing diagnosis in the fixed synthetic QA database; no acceptance gate.

Use the retained capacity run ID. No tables, objects, caches or counters are
cleared. Timed calls use actual Bearer authentication and the real ASGI routes.
Instrumentation exists only in this short-lived process, not the serving API.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime

import fastapi.routing
import httpx
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.passports import roster_cache, roster_view_service
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportSubmissionViewRepository,
)
from app.infrastructure.repositories.refresh_token_repository import (
    RefreshTokenRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.main import create_application
from app.presentation.api.v1.routes.passport_routes import queries
from capacity_fixtures import identifier
from qualification_application_journey import isolated
from sqlalchemy import event, select, text

TRACE = contextvars.ContextVar("capacity_diagnostic_trace", default=None)


def span(name, started, cpu_started):
    trace = TRACE.get()
    if trace is not None:
        trace.append(
            {
                "phase": name,
                "milliseconds": round((time.perf_counter() - started) * 1000, 3),
                "thread_cpu_ms": round((time.thread_time() - cpu_started) * 1000, 3),
            }
        )


def timed_sync(function, name):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        started, cpu = time.perf_counter(), time.thread_time()
        try:
            return function(*args, **kwargs)
        finally:
            span(name, started, cpu)

    return wrapped


def timed_async(function, name):
    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        started, cpu = time.perf_counter(), time.thread_time()
        try:
            return await function(*args, **kwargs)
        finally:
            span(name, started, cpu)

    return wrapped


async def main():
    isolated()
    run_id = os.environ.get("CAPACITY_DIAGNOSTIC_RUN_ID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise RuntimeError("A retained synthetic capacity run ID is required")
    group_id = identifier(run_id, "group-0")
    actors = []
    async with AsyncSessionFactory() as db:
        group = await db.get(ClientGroupModel, group_id)
        if group is None or group.agency_id != identifier(run_id, "agency-0"):
            raise RuntimeError("The retained synthetic group does not match its tenant")
        revision_before = group.roster_revision
        jit = await db.scalar(text("SHOW jit"))
        for index in (0, 1):
            repository = UserRepository(db)
            user = await repository.get_by_id(identifier(run_id, f"staff-0-{index}"))
            if user is None or user.agency_id != group.agency_id:
                raise RuntimeError("Synthetic actor scope mismatch")
            issued = await LoginUseCase(
                repository, RefreshTokenRepository(db)
            ).issue_session(user)
            actors.append((user.role.value, issued.access_token))
        await db.commit()
    # The fixture's issuance connection is not allowed to prime the HTTP probe.
    await engine.dispose()
    patches = [
        (PassportSubmissionViewRepository, "projection", "projection_total", True),
        (PassportSubmissionViewRepository, "revision", "revision_scope", True),
        (PassportSubmissionViewRepository, "page_details", "page_hydration", True),
        (
            roster_view_service,
            "prepare_submission_view",
            "duplicate_prepare_cpu",
            False,
        ),
        (roster_cache, "encode", "cache_encode_cpu", False),
        (roster_cache, "decode", "cache_decode_cpu", False),
        (queries, "build_view_response", "response_model_cpu", False),
        (fastapi.routing, "serialize_response", "response_serialization", True),
    ]
    originals = []
    for owner, attribute, name, asynchronous in patches:
        original = getattr(owner, attribute)
        originals.append((owner, attribute, original))
        setattr(
            owner,
            attribute,
            (timed_async if asynchronous else timed_sync)(original, name),
        )

    captured_reads = {}

    def before_sql(connection, cursor, statement, parameters, context, many):
        connection.info.setdefault("qa_sql_starts", []).append(
            (time.perf_counter(), time.thread_time())
        )
        if statement.startswith("SELECT") and "passport_submissions" in statement:
            key = hashlib.sha256(statement.encode()).hexdigest()[:12]
            captured_reads.setdefault(key, (statement, parameters))

    def after_sql(connection, cursor, statement, parameters, context, many):
        started, cpu = connection.info["qa_sql_starts"].pop()
        trace = TRACE.get()
        if trace is not None:
            table = next(
                (
                    name
                    for name in (
                        "passport_submissions",
                        "audit_chain_heads",
                        "audit_logs",
                        "client_groups",
                        "users",
                        "dashboard_sessions",
                    )
                    if name in statement
                ),
                "other",
            )
            span(
                "sql:"
                + table
                + ":"
                + hashlib.sha256(statement.encode()).hexdigest()[:12],
                started,
                cpu,
            )

    event.listen(engine.sync_engine, "before_cursor_execute", before_sql)
    event.listen(engine.sync_engine, "after_cursor_execute", after_sql)
    app = create_application()
    results = []
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://synthetic.test"
        ) as client:

            async def request(operation, actor_index, attempt):
                path = (
                    f"/api/v1/passports/groups/{group_id}/submissions-view?page_size=50&page=1"
                    if operation == "roster"
                    else "/api/v1/search?q=Traveller%2000%2000001&limit=12"
                )
                trace = []
                handle = TRACE.set(trace)
                lags = []

                async def heartbeat():
                    previous = time.perf_counter()
                    while True:
                        await asyncio.sleep(0.005)
                        observed = time.perf_counter()
                        lags.append(max(0, observed - previous - 0.005) * 1000)
                        previous = observed

                heartbeat_task = asyncio.create_task(heartbeat())
                started_at = datetime.now(UTC).isoformat()
                started = time.perf_counter()
                try:
                    response = await client.get(
                        path,
                        headers={"Authorization": f"Bearer {actors[actor_index][1]}"},
                    )
                    elapsed = (time.perf_counter() - started) * 1000
                    assert response.status_code == 200, response.status_code
                    data = response.json()
                    if operation == "roster":
                        assert data["group_total"] == 5000 and len(data["items"]) <= 50
                    else:
                        assert data and all(
                            row["group_id"] == str(group_id) for row in data
                        )
                    results.append(
                        {
                            "operation": operation,
                            "role": actors[actor_index][0],
                            "attempt": attempt,
                            "started_at": started_at,
                            "elapsed_ms": round(elapsed, 3),
                            "server_ms": response.headers.get("X-Response-Time-Ms"),
                            "loop_max_lag_ms": round(max(lags, default=0), 3),
                            "response_bytes": len(response.content),
                            "phases": trace,
                        }
                    )
                finally:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
                    TRACE.reset(handle)

            for actor in (0, 1):
                for attempt in (1, 2, 3):
                    await request("roster", actor, attempt)
                    await request("search", actor, attempt)
        async with AsyncSessionFactory() as db:
            revision_after = await db.scalar(
                select(ClientGroupModel.roster_revision).where(
                    ClientGroupModel.id == group_id
                )
            )
        assert revision_after == revision_before
    finally:
        for owner, attribute, original in originals:
            setattr(owner, attribute, original)
        event.remove(engine.sync_engine, "before_cursor_execute", before_sql)
        event.remove(engine.sync_engine, "after_cursor_execute", after_sql)
        await engine.dispose()
    plans = []
    # Explain the exact bound SELECTs captured above, in read-only transactions.
    # Preserve parameters only in memory; receipts contain no SQL or values.
    for key, (statement, parameters) in captured_reads.items():
        for jit_mode in ("on", "off"):
            async with engine.connect() as connection, connection.begin():
                await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                await connection.exec_driver_sql("SET LOCAL jit = " + jit_mode)
                await connection.exec_driver_sql(
                    "SET LOCAL statement_timeout = '10000'"
                )
                result = await connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
                    parameters,
                )
                plan = result.scalar_one()[0]
                plans.append(
                    {
                        "sql_sha256_prefix": key,
                        "jit_setting": jit_mode,
                        "plan": plan,
                    }
                )
    await engine.dispose()
    print(
        "CAPACITY_DIAGNOSTIC="
        + json.dumps(
            {
                "result": "passed",
                "run_id": run_id,
                "postgres_jit": jit,
                "roster_revision_before": revision_before,
                "roster_revision_after": revision_after,
                "cases": results,
                "read_only_query_plans": plans,
                "scope": "Fresh ASGI process on the retained synthetic 5000-row tenant; first requests retained; no cache/DB reset",
                "limits": "Single-process sequential diagnosis, no acceptance/throughput claim; async phase thread CPU includes interleaved main-thread work",
                "production_changed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
