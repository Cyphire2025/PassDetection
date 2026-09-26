"""Measure actual substring plans on a retained synthetic100k-row CI database.

Run after migrations on a newly-created passdetection_ci_search_* database.
No existing data is deleted. A populated database is refused so a benchmark
cannot accidentally grow repeatedly or run against production.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config.settings import get_settings  # noqa: E402
from app.domain.entities.entities import User, UserRole  # noqa: E402
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, PassportSubmissionModel, UserModel  # noqa: E402
from app.presentation.api.v1.routes.search import passport_search_statement  # noqa: E402


def main() -> int:
    database = os.environ["POSTGRES_DB"]
    if not database.startswith("passdetection_ci_search_"):
        raise RuntimeError("Explicit isolated search database required")
    engine = create_engine(get_settings().database.sync_url)
    with engine.connect() as connection:
        if connection.scalar(text("SELECT current_database()")) != database:
            raise RuntimeError("Database identity mismatch")
        if connection.scalar(text("SELECT count(*) FROM passport_submissions")):
            raise RuntimeError("Refusing to modify an already-populated benchmark")
    agency, owner, group, seed = (uuid.uuid4() for _ in range(4))
    with Session(engine) as session:
        session.add(AgencyModel(id=agency, name="Synthetic capacity agency", email=f"{agency}@example.test"))
        session.flush()
        session.add(UserModel(id=owner, agency_id=agency, email=f"{owner}@example.test", full_name="Synthetic staff", hashed_password="unused", role="agency_staff"))
        session.flush()
        session.add(ClientGroupModel(id=group, agency_id=agency, created_by_user_id=owner, name="Synthetic Search Group", token=f"synthetic-{group}"))
        session.flush()
        session.add(PassportSubmissionModel(id=seed, agency_id=agency, group_id=group, client_name="Seed passenger", image_s3_key="synthetic", status="submitted"))
        session.commit()
    with engine.begin() as connection:
        # Copy ORM-initialized defaults, then replace only synthetic identity and
        # searchable values. generate_series avoids100k ORM objects in memory.
        connection.execute(text("""
            INSERT INTO passport_submissions
            SELECT (jsonb_populate_record(NULL::passport_submissions,
                to_jsonb(p) || jsonb_build_object(
                    'id', md5('synthetic-search-' || n)::uuid,
                    'client_name', CASE WHEN n % 10000 = 0 THEN 'RareNeedle Passenger ' || n ELSE 'Passenger ' || n END,
                    'client_email', 'passenger' || n || '@example.test',
                    'client_phone', '+919' || lpad(n::text,9,'0'),
                    'extracted_fields', jsonb_build_object('passport_number', 'SYN' || lpad(n::text,9,'0'), 'surname', 'SURNAME' || n, 'given_names', 'GIVEN' || n),
                    'updated_at', now() - n * interval '1 second'
                ))).*
            FROM passport_submissions p CROSS JOIN generate_series(1,100000) n
            WHERE p.id = :seed
        """), {"seed": seed})
        connection.execute(text("ANALYZE passport_submissions"))
        connection.execute(text("ANALYZE client_groups"))
    user = User(id=owner, agency_id=agency, full_name="Synthetic staff", email="synthetic@example.test", hashed_password="unused", role=UserRole.AGENCY_STAFF)
    cases = {}
    with engine.connect() as connection:
        connection.execute(text("SET statement_timeout = '5s'"))
        for name, query in {"selective_name": "rareneedle", "selective_json": "SYN000054321", "absent": "absent-needle", "two_character": "pa", "group_name": "Synthetic Search Group"}.items():
            statement = passport_search_statement(user, query, 12)
            compiled = statement.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})
            # Compiled values are solely synthetic constants, never user input.
            plan = connection.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(compiled))).scalar_one()[0]
            timings = []
            for _ in range(20):
                start = time.perf_counter()
                rows = connection.execute(statement).all()
                timings.append((time.perf_counter() - start) * 1000)
            if len(rows) > 12:
                raise RuntimeError("Search exceeded its response bound")
            cases[name] = {"returned": len(rows), "p50_ms": round(statistics.median(timings), 2), "p95_ms": round(sorted(timings)[18], 2), "plan": plan}
        for name in ("selective_name", "selective_json", "absent"):
            if "ix_passport_search_trgm" not in json.dumps(cases[name]["plan"]):
                raise RuntimeError(f"Selective search did not use its index: {name}")
        indexes = connection.execute(text("SELECT indexrelname, pg_relation_size(indexrelid) FROM pg_stat_user_indexes WHERE indexrelname IN ('ix_passport_search_trgm','ix_client_group_search_trgm')")).all()
    report = {"database": database, "rows": 100001, "samples_per_case": 20, "limits": "Local synthetic PostgreSQL16; one large tenant/group, warm-cache measurements. Not VPS load or a multi-tenant production SLO.", "index_bytes": dict(indexes), "cases": cases}
    target = ROOT.parent / "docs/remediation/search-plan-evidence.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {k: v for k, v in case.items() if k != "plan"} for name, case in cases.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
