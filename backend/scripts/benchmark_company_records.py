"""Synthetic SQLite company-record helper benchmark; never production capacity proof.

Creates a new output directory, seeds in batches of 500, then runs at most four
concurrent readers for 20-120 seconds. Uses the actual application read helper,
but does not include HTTP, authentication middleware, Redis or PostgreSQL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sqlite3
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def identifier(kind: int, number: int = 0) -> uuid.UUID:
    return uuid.UUID(int=((0xF0000000 | kind) << 96) + number + 1)


async def measure(output: Path, records: int, seconds: int, concurrency: int) -> dict:
    # Isolate configuration before importing any application dependency. There
    # is no .env file in the newly created output directory, and no service call.
    os.chdir(output)
    os.environ.update(APP_ENV="development", APP_SECRET_KEY="synthetic-company-records-only",
                      POSTGRES_HOST="127.0.0.1", POSTGRES_PORT="1", POSTGRES_PASSWORD="synthetic-only",
                      S3_ACCESS_KEY_ID="synthetic-only", S3_SECRET_ACCESS_KEY="synthetic-only")
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import event, insert, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import AsyncAdaptedQueuePool

    from app.core.config.settings import Settings
    from app.domain.entities.entities import User, UserRole
    from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
    from app.infrastructure.database.model_base import Base
    from app.infrastructure.database.models import (
        AgencyModel,
        ClientGroupModel,
        PassportSubmissionModel,
    )
    from app.presentation.api.v1.routes.company_submissions import company_submissions

    path = output / "synthetic-company-records.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}", poolclass=AsyncAdaptedQueuePool,
                                 pool_size=concurrency, max_overflow=0)

    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA cache_size=-8192")
        cursor.close()

    agency, client = identifier(1), identifier(2)
    started = time.perf_counter()
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(insert(AgencyModel), {"id": agency, "name": "Synthetic operator", "email": "operator@example.invalid"})
        await connection.execute(insert(ClientOrganizationModel), {"id": client, "agency_id": agency,
            "name": "Synthetic client", "normalized_name": "synthetic client"})
        await connection.execute(insert(ClientGroupModel), [{"id": identifier(3, index), "agency_id": agency,
            "company_id": client, "name": f"Synthetic trip {index}", "token": f"synthetic-unusable-{index}",
            "status": ("active", "closed", "archived")[index % 3]} for index in range(100)])
        for start in range(0, records, 500):
            await connection.execute(insert(PassportSubmissionModel), [{"id": identifier(4, index),
                "agency_id": agency, "group_id": identifier(3, index % 100),
                "client_name": f"Synthetic Traveller {index:06d}", "image_s3_key": "synthetic-no-document",
                "status": "staff_approved", "created_at": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
                "extracted_fields": {"given_names": "Synthetic", "surname": f"Traveller {index:06d}"}}
                for index in range(start, min(start + 500, records))])
        await connection.execute(text("ANALYZE"))
    seed_seconds = time.perf_counter() - started
    actor = User.create(email="reader@example.invalid", hashed_password="synthetic-unusable",
                        full_name="Synthetic reader", role=UserRole.AGENCY_ADMIN, agency_id=agency)
    settings = Settings(_env_file=None, app_env="development")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    statements: dict[str, tuple] = {}

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.startswith("SELECT") and len(statements) < 4:
            statements.setdefault(statement, parameters)

    samples: dict[str, list[float]] = {"first_page": [], "cursor_page": [], "name_search": []}
    failures = 0
    maximum_returned = 0
    deadline = time.perf_counter() + seconds

    async def reader(worker: int):
        nonlocal failures, maximum_returned
        cursor = None
        iteration = worker
        while time.perf_counter() < deadline:
            kind = "name_search" if iteration % 5 == 0 else "cursor_page" if cursor else "first_page"
            started = time.perf_counter()
            try:
                async with sessions() as session:
                    result = await company_submissions(company_id=client, agency_id=agency,
                        search="Traveller 000001" if kind == "name_search" else "",
                        cursor=cursor if kind == "cursor_page" else None, page_size=25,
                        user=actor, session=session, settings=settings)
                maximum_returned = max(maximum_returned, len(result.items))
                assert len(result.items) <= 25
                if kind == "name_search":
                    assert len(result.items) == 1 and result.items[0].id == identifier(4, 1)
                else:
                    assert len(result.items) == 25
                    cursor = result.next_cursor if kind == "first_page" else None
                # Bound retained timings independently from throughput.
                if len(samples[kind]) < 10000:
                    samples[kind].append((time.perf_counter() - started) * 1000)
            except Exception:
                failures += 1
                raise
            iteration += 1

    load_started = time.perf_counter()
    await asyncio.gather(*(reader(index) for index in range(concurrency)))
    elapsed = time.perf_counter() - load_started
    from app.presentation.api.v1.routes.companies import company_summary
    summary_started = time.perf_counter()
    async with sessions() as session:
        summary = await company_summary(company_id=client, agency_id=agency, user=actor, session=session)
    summary_ms = (time.perf_counter() - summary_started) * 1000
    assert summary.collected_records == records and summary.unresolved_historical_records == records
    assert summary.total_groups == 100 and summary.unique_travellers == 0 and summary.identity_totals_partial
    plans = []
    async with engine.connect() as connection:
        for statement, parameters in statements.items():
            rows = (await connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)).all()
            plans.append({"sql": statement, "plan": [row[-1] for row in rows]})
    await engine.dispose()

    def stats(values: list[float]) -> dict:
        ordered = sorted(values)
        return {"sampled_operations": len(values), **{name: round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * quantile))], 3)
            for name, quantile in (("p50_ms", .5), ("p95_ms", .95), ("p99_ms", .99))}}

    peak = None
    if os.name == "nt":
        import subprocess
        peak = int(subprocess.check_output(["powershell", "-NoProfile", "-Command",
            f"(Get-Process -Id {os.getpid()}).PeakWorkingSet64"], text=True, timeout=10).strip())
    return {"dataset": {"collected_records": records, "client_companies": 1, "assigned_groups": 100},
        "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "platform": platform.system()},
        "seed_batch_size": 500, "seed_seconds": round(seed_seconds, 3), "concurrent_readers": concurrency,
        "elapsed_seconds": round(elapsed, 3), "errors": failures, "max_records_returned": maximum_returned,
        "database_bytes": path.stat().st_size, "peak_working_set_bytes": peak,
        "summary_single_sample_ms": round(summary_ms, 3),
        "latencies": {name: stats(values) for name, values in samples.items()}, "query_plans": plans,
        "limitations": ["Synthetic SQLite application-helper benchmark, not PostgreSQL or HTTP capacity",
            "No OTP, document bytes, authentication middleware or network", "No million-user or sustained-production claim",
            "SQLite name search does not provide the production PostgreSQL trigram index"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--records", type=int, default=100000)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--readers", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    if not 50000 <= args.records <= 100000 or not 20 <= args.seconds <= 120:
        parser.error("Use 50000-100000 records and 20-120 seconds.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(measure(output, args.records, args.seconds, args.readers))
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "query_plans"}, indent=2))


if __name__ == "__main__":
    main()
