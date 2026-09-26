"""Retained synthetic ASGI handler benchmark in the actual backend runtime image."""

from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import sys
import time
import tracemalloc
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.security.jwt import create_access_token  # noqa: E402
from app.infrastructure.database.models import (  # noqa: E402
    AgencyModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import AsyncSessionFactory, engine  # noqa: E402
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportSubmissionViewRepository,  # noqa: E402
)
from app.infrastructure.repositories.refresh_token_repository import (
    RefreshTokenRepository,  # noqa: E402
)
from app.main import create_application  # noqa: E402


async def main() -> None:
    if not os.environ.get("POSTGRES_DB", "").startswith("passdetection_ci_roster"):
        raise RuntimeError("An explicitly isolated roster qualification database is required")
    run_id = uuid.uuid4()
    tokens, groups = [], []
    async with AsyncSessionFactory() as session:
        agency = AgencyModel(id=uuid.uuid4(), name="Synthetic roster load", email=f"{run_id}@example.test")
        session.add(agency)
        await session.flush()
        users = [UserModel(id=uuid.uuid4(), agency_id=agency.id, role="agency_staff", full_name=f"Synthetic staff {i}",
                           email=f"{run_id}-{i}@example.test", hashed_password="unused") for i in range(4)]
        session.add_all(users)
        await session.flush()
        for user in users:
            session.add(UserSecurityStateModel(user_id=user.id, credential_state="active", session_version=1))
            family = await RefreshTokenRepository(session).save(str(uuid.uuid4()), user.id, datetime.now(UTC) + timedelta(days=1))
            tokens.append(create_access_token(user.id, user.role, agency.id, session_id=family.session_id)[0])
        for count, duplicate in ((250, False), (1000, False), (5000, False), (5000, True)):
            group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, created_by_user_id=users[0].id,
                                     token=uuid.uuid4().hex, name="Synthetic roster load")
            session.add(group)
            await session.flush()
            session.add_all([ManagerGroupAccessModel(manager_id=user.id, group_id=group.id, agency_id=agency.id) for user in users[1:]])
            await session.flush()
            await session.execute(insert(PassportSubmissionModel), [dict(
                id=uuid.uuid4(), agency_id=agency.id, group_id=group.id, client_name=f"Synthetic passenger {i:06}",
                image_s3_key="synthetic", status="submitted",
                extracted_fields={"passport_number": "DUPLICATE" if duplicate else f"SYN{i:09}", "place_of_issue": "Chennai"},
            ) for i in range(count)])
            groups.append((group.id, count, duplicate))
        await session.commit()

    queries = 0
    projections = 0
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_query(*args):
        nonlocal queries
        queries += 1
    original = PassportSubmissionViewRepository.projection
    async def counted(self, **kwargs):
        nonlocal projections
        projections += 1
        return await original(self, **kwargs)
    PassportSubmissionViewRepository.projection = counted
    cases = []
    app = create_application()
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://synthetic.test") as client:
            async def request(group_id, actor, page, *, cold=False):
                start = time.perf_counter()
                params = {"page": page, "page_size": 50}
                if cold:
                    params["search"] = ""  # distinct cache identity, identical filter semantics
                response = await client.get(f"/api/v1/passports/groups/{group_id}/submissions-view", params=params,
                                            headers={"Authorization": f"Bearer {tokens[actor]}"})
                if response.status_code != 200:
                    raise RuntimeError(f"Synthetic roster request failed: {response.status_code} {response.text[:200]}")
                data = response.json()
                assert data["returned_count"] <= 50
                return (time.perf_counter() - start) * 1000, len(response.content), data
            for group_id, count, duplicate in groups:
                start_queries, start_projections = queries, projections
                cold = await asyncio.gather(*(request(group_id, actor, 1) for actor in range(4)))
                cold_queries, cold_projections = queries - start_queries, projections - start_projections
                start_queries, start_projections = queries, projections
                timings, payloads = [], []
                for iteration in range(20):
                    batch = await asyncio.gather(*(request(group_id, actor, 1 + iteration % min(4, math.ceil(count / 50))) for actor in range(4)))
                    for elapsed, size, data in batch:
                        assert data["total"] == count
                        timings.append(elapsed)
                        payloads.append(size)
                warm_queries, warm_projections = queries - start_queries, projections - start_projections
                if warm_projections != 0:
                    raise RuntimeError(f"Warm roster recomputed projection {warm_projections} times")
                allocations = {}
                for mode in ("cold", "warm"):
                    tracemalloc.start()
                    await request(group_id, 0, 1, cold=mode == "cold")
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    allocations[mode + "_peak_python_bytes"] = peak
                ordered = sorted(timings)
                cases.append({"rows": count, "single_duplicate_cluster": duplicate, "concurrent_staff": 4,
                    "cold_samples": 4, "cold_p95_ms": round(max(item[0] for item in cold), 2),
                    "cold_sql_per_request": cold_queries / 4, "cold_projection_calls": cold_projections,
                    "warm_samples": len(timings), "warm_p50_ms": round(statistics.median(timings), 2),
                    "warm_p95_ms": round(ordered[math.ceil(len(ordered) * .95)-1], 2),
                    "warm_p99_ms": round(ordered[math.ceil(len(ordered) * .99)-1], 2),
                    "warm_sql_per_request": warm_queries / len(timings), "warm_projection_calls": warm_projections,
                    "maximum_response_bytes": max(payloads), **allocations})
    finally:
        PassportSubmissionViewRepository.projection = original
        event.remove(engine.sync_engine, "before_cursor_execute", count_query)
        await engine.dispose()
    print("ROSTER_EVIDENCE=" + json.dumps({"cases": cases, "scope": "Actual backend runtime image; real PostgreSQL and Redis; ASGI authenticated API requests, including response serialization. Four concurrent staff in one process. Excludes public-network latency and is not a VPS SLO. Python tracemalloc peaks sampled separately from latency runs; no synthetic rows or volumes deleted."}, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
