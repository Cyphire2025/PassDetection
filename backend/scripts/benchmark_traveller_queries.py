"""Bounded synthetic local query benchmark; NOT PostgreSQL/API capacity proof.

Run from backend with .venv311 Python. Creates a new synthetic SQLite database
under the specified output directory; refuses to overwrite an existing database.
No .env, provider, real record, or network service is accessed. Batches cap Python
working data at 500 rows. Concurrent readers are capped at four for 20-300 seconds.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import random
import sqlite3
import statistics
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine, insert

from app.infrastructure.database import gc_mobile_models  # noqa: F401
from app.infrastructure.database.model_base import Base
from app.infrastructure.database.models import AgencyModel, ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
)

SYNTHETIC_KEY = b"synthetic-benchmark-only-lookup-key"


def identity(kind: int, index: int) -> uuid.UUID:
    # SQLite gives PostgreSQL's UUID type numeric affinity. A leading hex letter
    # prevents numeric-only synthetic UUIDs collapsing through float conversion.
    return uuid.UUID(int=((0xF0000000 | kind) << 96) + index + 1)


def fingerprint(index: int) -> str:
    return hmac.new(SYNTHETIC_KEY, str(index).encode(), hashlib.sha256).hexdigest()


def peak_memory_bytes() -> int | None:
    if os.name != "nt":
        return None
    result = subprocess.run(["powershell", "-NoProfile", "-Command",
        f"(Get-Process -Id {os.getpid()}).PeakWorkingSet64"], capture_output=True, text=True, check=True)
    return int(result.stdout.strip())


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile_value))], 3)


def seed(path: Path, profile_count: int) -> tuple[str, float]:
    started = time.perf_counter()
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.exec_driver_sql("PRAGMA cache_size=-32768")
        Base.metadata.create_all(connection)
        agency_id = identity(1, 0)
        connection.execute(insert(AgencyModel), [{"id": agency_id, "name": "Synthetic load fixture", "email": "fixture@example.invalid"}])
        connection.execute(insert(gc_mobile_models.ClientOrganizationModel), [
            {"id": identity(2, index), "agency_id": agency_id, "name": f"Company {index:04d}", "normalized_name": f"company {index:04d}"}
            for index in range(250)
        ])
        connection.execute(insert(ClientGroupModel), [
            {"id": identity(3, index), "agency_id": agency_id, "company_id": identity(2, 0),
             "company_revision": 1, "name": f"Synthetic trip {index}", "token": f"synthetic-{index}"}
            for index in range(101)
        ])
        for start in range(0, profile_count, 500):
            indices = range(start, min(start + 500, profile_count))
            connection.execute(insert(TravellerProfileModel), [
                {"id": identity(4, index), "agency_id": agency_id, "company_id": identity(2, 0),
                 "status": "active", "reuse_permission_status": "unknown"}
                for index in indices
            ])
            connection.execute(insert(TravellerPassportModel), [
                {"id": identity(5, index), "agency_id": agency_id, "company_id": identity(2, 0),
                 "traveller_id": identity(4, index), "issuing_country": "IND", "document_type": "P",
                 "number_fingerprint": fingerprint(index), "fingerprint_key_version": "synthetic",
                 "number_ciphertext": "synthetic-unusable-placeholder", "status": "accepted", "is_default": True}
                for index in indices
            ])
            for trip in range(2):
                connection.execute(insert(TravellerParticipationModel), [
                    {"id": identity(6 + trip, index), "agency_id": agency_id, "company_id": identity(2, 0),
                     "traveller_id": identity(4, index), "group_id": identity(3, 0 if index < 700 and trip == 0 else 1 + (index + trip) % 100),
                     "source_kind": "synthetic", "idempotency_key": f"synthetic-{index}-{trip}",
                     "profile_revision": 1, "contact_revision": 1, "question_version": "synthetic", "status": "accepted"}
                    for index in indices
                ])
        connection.exec_driver_sql("ANALYZE")
    engine.dispose()
    return agency_id.hex, time.perf_counter() - started


QUERIES = {
    "company_search": "SELECT id,name,status FROM client_organizations WHERE agency_id=? AND status='active' AND normalized_name >= 'company 0200' ORDER BY normalized_name,id LIMIT 30",
    "passport_lookup": "SELECT id,traveller_id FROM traveller_passports WHERE agency_id=? AND company_id=? AND fingerprint_key_version='synthetic' AND number_fingerprint=? LIMIT 2",
    "traveller_page": "SELECT id,status FROM traveller_profiles WHERE agency_id=? AND company_id=? AND status='active' AND id>? ORDER BY id LIMIT 50",
    "group_summary": "SELECT status,count(*) FROM traveller_participations WHERE agency_id=? AND company_id=? AND group_id=? GROUP BY status",
}


def read_load(path: Path, agency: str, profile_count: int, seconds: int, worker: int):
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
    connection.execute("PRAGMA cache_size=-8192")
    deadline = time.perf_counter() + seconds
    random_source = random.Random(worker)
    samples: dict[str, list[float]] = {name: [] for name in QUERIES}
    counts = {name: 0 for name in QUERIES}
    errors = 0
    company = identity(2, 0).hex
    while time.perf_counter() < deadline:
        index = random_source.randrange(profile_count)
        parameters = {
            "company_search": (agency,), "passport_lookup": (agency, company, fingerprint(index)),
            "traveller_page": (agency, company, identity(4, index).hex),
            "group_summary": (agency, company, identity(3, random_source.randrange(101)).hex),
        }
        for name, query in QUERIES.items():
            started = time.perf_counter()
            try:
                connection.execute(query, parameters[name]).fetchall()
                counts[name] += 1
                elapsed = (time.perf_counter() - started) * 1000
                # Deterministic bounded reservoir: do not retain all requests.
                if len(samples[name]) < 5000:
                    samples[name].append(elapsed)
                else:
                    slot = random_source.randrange(counts[name])
                    if slot < 5000:
                        samples[name][slot] = elapsed
            except sqlite3.Error:
                errors += 1
    connection.close()
    return samples, counts, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=int, choices=(50_000, 100_000), default=50_000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=20)
    args = parser.parse_args()
    if not 20 <= args.duration_seconds <= 300:
        raise SystemExit("Read duration must be between 20 and 300 seconds")
    args.output.mkdir(parents=True, exist_ok=True)
    database = args.output / f"synthetic-{args.profiles}.sqlite"
    if database.exists():
        raise SystemExit("Refusing to overwrite an existing synthetic fixture")
    agency, seed_seconds = seed(database, args.profiles)
    print(json.dumps({"event": "seeded", "profiles": args.profiles, "seconds": round(seed_seconds, 2)}), flush=True)
    peak_before = peak_memory_bytes()
    if peak_before is not None and peak_before > 768 * 1024 * 1024:
        raise SystemExit("Stopped before concurrent reads: 768MiB process budget exceeded")
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda worker: read_load(database, agency, args.profiles, args.duration_seconds, worker), range(4)))
    duration = time.perf_counter() - started
    measured = {}
    for name in QUERIES:
        samples = [value for result in results for value in result[0][name]]
        total = sum(result[1][name] for result in results)
        measured[name] = {"requests": total, "throughput_per_second": round(total / duration, 1),
            "p50_ms": percentile(samples, .5), "p95_ms": percentile(samples, .95),
            "p99_ms": percentile(samples, .99), "mean_ms": round(statistics.mean(samples), 3)}
    with sqlite3.connect(database) as connection:
        plan_params = {
            "company_search": (agency,), "passport_lookup": (agency, identity(2, 0).hex, fingerprint(40)),
            "traveller_page": (agency, identity(2, 0).hex, identity(4, 40).hex),
            "group_summary": (agency, identity(2, 0).hex, identity(3, 0).hex),
        }
        plans = {name: connection.execute("EXPLAIN QUERY PLAN " + query, plan_params[name]).fetchall() for name, query in QUERIES.items()}
        fixture_700 = connection.execute("SELECT count(*) FROM traveller_participations WHERE group_id=?", (identity(3, 0).hex,)).fetchone()[0]
    report = {"engine": f"SQLite {sqlite3.sqlite_version}", "qualification": "local query-shape test only; NOT production/API/PostgreSQL capacity",
        "platform": platform.platform(), "cpu_logical_count": os.cpu_count(), "python": platform.python_version(),
        "profiles": args.profiles, "passports": args.profiles, "participations": args.profiles * 2,
        "companies": 250, "groups": 101, "large_group_participations": fixture_700,
        "concurrent_readers": 4, "duration_seconds": round(duration, 2), "seed_seconds": round(seed_seconds, 2),
        "peak_working_set_bytes": peak_memory_bytes(), "database_bytes": database.stat().st_size,
        "error_count": sum(result[2] for result in results), "measurements": measured, "query_plans": plans,
        "not_tested": ["HTTP/API latency", "PostgreSQL locks/concurrency", "writes under load", "OTP providers", "OCR", "queues", "multi-hour soak", "million-record dataset"]}
    output = args.output / f"results-{args.profiles}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"result": str(output), "errors": report["error_count"], "peak_bytes": report["peak_working_set_bytes"]}), flush=True)


if __name__ == "__main__":
    main()
