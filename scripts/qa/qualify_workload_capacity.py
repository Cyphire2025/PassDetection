"""Measure a declared synthetic HTTP workload against the fixed local QA stack.

The runner cannot accept a URL, database, project or credential override. It
performs real TLS/proxy/API/database/Redis/storage/scanner/worker calls using
fresh test-only records. No production service or external provider is used.
Run after the capacity overlay is started, with no other qualification traffic.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import random
import subprocess
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime

import httpx
from capacity_container_events import capture as capture_container_events
from capacity_container_events import gates as container_event_gates
from mcp_capacity import MCP_BUDGETS_MS, paced_reads, serialized_exports
from mcp_capacity import gates as mcp_gates
from mcp_capacity_profile import (
    EXPORT_FAMILIES,
    EXPORT_SCHEDULING,
    SOURCE_BYTES,
    SOURCE_ROWS,
    require_minimum_profile,
)
from PIL import Image
from run_qualification_stack import COMPOSE, OUTPUT, ROOT

ORIGIN = "https://localhost:58443"
FIXTURES = [
    *COMPOSE,
    "exec",
    "-T",
    "backend",
    "python",
    "/workspace/scripts/qa/capacity_fixtures.py",
]
# Set before measurements. The short lane is an operating-envelope check, not
# a long-running soak or external-AI throughput qualification.
BUDGETS_MS = {
    **MCP_BUDGETS_MS,
    "stats": (750, 1500),
    "notifications": (500, 1000),
    "search": (1000, 2000),
    "roster": (1500, 3000),
    "scan": (1000, 2000),
    "upload": (8000, 15000),
}
EXPECTED_SECONDS = 60
OVERLOAD_SECONDS = 15
RECOVERY_SECONDS = 30
OBSERVATION_SECONDS = 220
# The existing global latency warning is 2s p95. The 5s overload p99 is a new
# explicit engineering ceiling, below the client's 20s transport timeout;
# it is declared before the next run, not presented as an approved user SLO.
OVERLOAD_BUDGET_MS = (2000, 5000)
MAX_PENDING_AGE_SECONDS = 900
RECOVERY_DEADLINE_SECONDS = 300
EXPECTED_SCAN_REQUESTS = 60
EXPECTED_UNIQUE_SCANS = 30
OBSERVED_QUEUES = ("passport_ocr", "ecr_checks")
API_MEMORY_BYTES = 2560 * 1024**2


def fixture(action: str, run_id: str) -> dict:
    result = subprocess.run(
        [*FIXTURES, action, run_id],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=150,
        check=True,
    )
    # The seed includes short-lived synthetic access tokens. They stay in
    # memory and must not be included in retained reports or console output.
    return json.loads(result.stdout.strip().splitlines()[-1])


def percentile(values: list[float], fraction: float) -> float:
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3)


def summarize(samples: list[dict]) -> dict:
    groups = defaultdict(list)
    for sample in samples:
        groups[sample["operation"]].append(sample)
    result = {}
    for operation, observations in sorted(groups.items()):
        values = [row["milliseconds"] for row in observations]
        result[operation] = {
            "requests": len(values),
            "p50_ms": percentile(values, 0.5),
            "p95_ms": percentile(values, 0.95),
            "p99_ms": percentile(values, 0.99),
            "maximum_ms": round(max(values), 3),
            "statuses": dict(Counter(str(row["status"]) for row in observations)),
            "contract_failures": sum(not row["valid"] for row in observations),
            "max_response_bytes": max(row["bytes"] for row in observations),
        }
    return result


async def measured(
    client: httpx.AsyncClient,
    samples: list[dict],
    operation: str,
    method: str,
    path: str,
    *,
    actor: dict | None = None,
    overload: bool = False,
    **arguments,
) -> httpx.Response | None:
    headers = dict(arguments.pop("headers", {}))
    if actor:
        headers["Cookie"] = f"access_token={actor['token']}"
        headers["Origin"] = ORIGIN
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    status, count, valid = 0, 0, False
    response = None
    try:
        response = await client.request(method, path, headers=headers, **arguments)
        status, count = response.status_code, len(response.content)
        expected = 201 if operation == "upload" else 200
        valid = status == expected and "application/json" in response.headers.get(
            "content-type", ""
        )
        if overload and status == 429:
            body = response.json()
            retry_after = response.headers.get("retry-after", "")
            valid = body.get("error", {}).get("code") in {
                "DASHBOARD_RATE_LIMITED",
                "APP_RATE_LIMITED",
                "RATE_LIMIT_EXCEEDED",
            } and (retry_after.isdigit() and int(retry_after) > 0)
        elif valid:
            body = response.json()
            if operation == "roster":
                valid = (
                    len(body["items"]) <= 50
                    and body["group_total"] == actor["group_size"]
                )
                valid = valid and all(
                    row["group_id"] == actor["group_id"] for row in body["items"]
                )
            elif operation == "search":
                valid = 1 <= len(body) <= 12 and all(
                    row["group_id"] == actor["group_id"] for row in body
                )
            elif operation == "scan":
                valid = body["status"] in {"counted", "duplicate"}
            elif operation == "upload":
                valid = (
                    bool(body.get("passport_cover_s3_key"))
                    and body.get("processing_job_id") is None
                )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        valid = False
    samples.append(
        {
            "operation": operation,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "server_milliseconds": response.headers.get("X-Response-Time-Ms")
            if response is not None
            else None,
            "request_id": response.headers.get("X-Request-ID")
            if response is not None
            else None,
            "status": status,
            "bytes": count,
            "milliseconds": (time.perf_counter() - started) * 1000,
            "valid": valid,
            "cohort": (
                "large_tenant" if actor["group_size"] >= 1000 else "small_tenant"
            )
            if actor
            else "public_upload",
        }
    )
    return response


def path_for(actor: dict, iteration: int) -> tuple[str, str]:
    return (
        ("stats", "/api/v1/dashboard/stats"),
        ("notifications", "/api/v1/notifications/feed?unread_only=false&limit=10"),
        (
            "roster",
            f"/api/v1/passports/groups/{actor['group_id']}/submissions-view?page_size=50&page=1",
        ),
        (
            "search",
            f"/api/v1/search?q=Traveller%20{actor['tenant']:02d}%2000001&limit=12",
        ),
        (
            "roster",
            f"/api/v1/passports/groups/{actor['group_id']}/submissions-view?page_size=50&page=2",
        ),
    )[iteration % 5]


async def paced_actor(
    client: httpx.AsyncClient,
    samples: list[dict],
    actor: dict,
    seconds: int,
    index: int,
) -> None:
    start = time.monotonic()
    await asyncio.sleep(index / 20)
    iteration = 0
    while time.monotonic() - start < seconds:
        operation, path = path_for(actor, iteration)
        await measured(client, samples, operation, "GET", path, actor=actor)
        iteration += 1
        await asyncio.sleep(max(0, start + iteration + index / 20 - time.monotonic()))


async def scans(
    client: httpx.AsyncClient, samples: list[dict], seed: dict, seconds: int
) -> None:
    start = time.monotonic()
    for index in range(seconds):
        actor = seed["coordinators"][index % len(seed["coordinators"])]
        # Repeat each event once after the initial delivery, retaining the same
        # durable event identity so the API's idempotency is exercised under load.
        logical = index // 20
        await measured(
            client,
            samples,
            "scan",
            "POST",
            f"/api/v1/tour-operations/coordinator/sessions/{actor['session_id']}/scan",
            actor=actor,
            json={
                "qr_payload": actor["qr_payloads"][logical],
                "client_event_id": f"capacity-{seed['run_id']}-{index % 10}-{logical}",
                "sync_source": "online",
            },
        )
        await asyncio.sleep(max(0, start + index + 1 - time.monotonic()))


def synthetic_jpeg(run_id: str, page: int) -> bytes:
    # Different content for every page and run prevents scanner-cache hits from
    # being mistaken for sustained document-ingestion capacity.
    generator = random.Random(f"{run_id}-{page}")
    image = Image.frombytes("RGB", (1200, 800), generator.randbytes(1200 * 800 * 3))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


async def uploads(
    client: httpx.AsyncClient, samples: list[dict], seed: dict, pages: list[bytes]
) -> None:
    start = time.monotonic()
    # Four uploads/minute; two real ~0.8MB JPEG pages are scanned and persisted.
    # No OCR provider is required by the public cover-only configuration.
    for index in range(4):
        await asyncio.sleep(max(0, start + index * 15 - time.monotonic()))
        capability = uuid.uuid4().hex
        await measured(
            client,
            samples,
            "upload",
            "POST",
            f"/api/v1/passports/upload/{seed['groups'][index]['public_token']}",
            headers={"X-Upload-Session-ID": capability},
            data={
                "client_name": "Synthetic capacity upload",
                "acquisition_mode": "file",
                "upload_idempotency_key": capability,
            },
            files={
                "passport_cover_file": (
                    "synthetic-front.jpg",
                    pages[index * 2],
                    "image/jpeg",
                ),
                "passport_back_cover_file": (
                    "synthetic-back.jpg",
                    pages[index * 2 + 1],
                    "image/jpeg",
                ),
            },
        )


async def overload_actor(
    client: httpx.AsyncClient, samples: list[dict], actor: dict
) -> None:
    stop = time.monotonic() + OVERLOAD_SECONDS
    while time.monotonic() < stop:
        await measured(
            client,
            samples,
            "stats",
            "GET",
            "/api/v1/dashboard/stats",
            actor=actor,
            overload=True,
        )


def gates(
    stages: dict,
    metrics: list[dict],
    job_verification: dict,
    samples: dict,
    windows: dict,
    queues_published_at: str,
) -> list[str]:
    failures = []
    observed_times = [datetime.fromisoformat(row["at"]).timestamp() for row in metrics]
    for stage, window in windows.items():
        start = datetime.fromisoformat(window["started_at"]).timestamp()
        end = datetime.fromisoformat(window["finished_at"]).timestamp()
        within = [
            instant for instant in observed_times if start - 4 <= instant <= end + 4
        ]
        if not within or min(within) > start + 4 or max(within) < end - 4:
            failures.append(f"{stage}:resource_observation_does_not_cover_stage")
    for stage in ("expected", "recovery"):
        office_reads = sum(
            row["operation"] in {"stats", "notifications", "roster", "search"}
            for row in samples[stage]
        )
        if office_reads / windows[stage]["elapsed_seconds"] < 19:
            failures.append(f"{stage}:achieved_office_throughput_below_19rps")
        for operation, result in stages[stage].items():
            p95, p99 = BUDGETS_MS[operation]
            if (
                result["contract_failures"]
                or result["p95_ms"] > p95
                or result["p99_ms"] > p99
            ):
                failures.append(f"{stage}:{operation}:contract_or_latency_budget")
        # Large groups must not disappear inside a pooled percentile dominated
        # by the nine smaller tenants. Apply the same existing operation floors.
        for cohort in ("large_tenant", "small_tenant"):
            cohort_results = summarize(
                [row for row in samples[stage] if row["cohort"] == cohort]
            )
            if not cohort_results:
                failures.append(f"{stage}:{cohort}:missing_observations")
            for operation, result in cohort_results.items():
                p95, p99 = BUDGETS_MS[operation]
                if result["p95_ms"] > p95 or result["p99_ms"] > p99:
                    failures.append(f"{stage}:{cohort}:{operation}:latency_budget")
    for operation, result in stages["cold"].items():
        if result["contract_failures"] or result["p99_ms"] > 5000:
            failures.append(f"cold:{operation}:contract_or_5s_budget")
    overload = stages["overload"]["stats"]
    if overload["contract_failures"] or int(overload["statuses"].get("429", 0)) == 0:
        failures.append("overload:missing_bounded_retryable_backpressure")
    if (
        overload["p95_ms"] > OVERLOAD_BUDGET_MS[0]
        or overload["p99_ms"] > OVERLOAD_BUDGET_MS[1]
    ):
        failures.append("overload:latency_budget")
    if any(
        row["oldest_pending_age_seconds"] >= MAX_PENDING_AGE_SECONDS for row in metrics
    ):
        failures.append("durable_queue:pending_age_budget")
    if not metrics or any(
        not isinstance(row.get("queues"), dict)
        or not all(name in row["queues"] for name in OBSERVED_QUEUES)
        for row in metrics
    ):
        failures.append("durable_queue:missing_queue_observation")
    drain_seconds = observed_queue_drain_seconds(metrics, queues_published_at)
    if drain_seconds is None or drain_seconds > RECOVERY_DEADLINE_SECONDS:
        failures.append("durable_queue:recovery_deadline")
    if not metrics or any(
        row["database_connections"] > row["database_max_connections"] - 10
        for row in metrics
    ):
        failures.append("database_connection_reserve")
    if (
        metrics
        and max(row["backend_cgroup_memory_bytes"] for row in metrics) > API_MEMORY_BYTES
    ):
        failures.append("backend_memory_budget")
    if job_verification.get("durable_jobs_verified") != 100:
        failures.append("durable_retry_recovery")
    scan_samples = [row for row in samples["expected"] if row["operation"] == "scan"]
    if len(scan_samples) != EXPECTED_SCAN_REQUESTS or any(
        not row["valid"] for row in scan_samples
    ):
        failures.append("scan_request_count_or_contract")
    if job_verification.get("persisted_unique_scans") != EXPECTED_UNIQUE_SCANS:
        failures.append("scan_retry_created_wrong_record_count")
    if (
        job_verification.get("persisted_uploads") != 4
        or job_verification.get("distinct_readable_upload_objects") != 8
    ):
        failures.append("uploaded_records_and_objects_not_verified")
    failures.extend(mcp_gates(samples, windows, metrics))
    return failures


def observed_queue_drain_seconds(
    metrics: list[dict], published_at: str
) -> float | None:
    """Require three consecutive empty samples after every delivery is published.

    Pre-enqueue zeroes cannot prove recovery, nor can one transient zero while
    work is redelivered. A missing/short observation remains unverified.
    """
    published = datetime.fromisoformat(published_at).timestamp()
    consecutive = 0
    for row in metrics:
        instant = datetime.fromisoformat(row["at"]).timestamp()
        if instant < published:
            continue
        queues = row.get("queues")
        empty = row.get("pending_durable_jobs") == 0 and isinstance(queues, dict) and all(
            name in queues and queues[name] == 0 for name in OBSERVED_QUEUES
        )
        consecutive = consecutive + 1 if empty else 0
        if consecutive == 3:
            return round(instant - published, 3)
    return None


def begin_stage(windows: dict, name: str) -> None:
    windows[name] = {
        "started_at": datetime.now(UTC).isoformat(),
        "clock": time.monotonic(),
    }


def end_stage(windows: dict, name: str, samples: list[dict]) -> None:
    stage = windows[name]
    stage["finished_at"] = datetime.now(UTC).isoformat()
    stage["elapsed_seconds"] = time.monotonic() - stage.pop("clock")
    stage["achieved_requests_per_second"] = len(samples) / stage["elapsed_seconds"]


async def tenant_negatives(client: httpx.AsyncClient, seed: dict) -> None:
    for actor in seed["actors"]:
        other = seed["groups"][(actor["tenant"] + 1) % 10]
        headers = {"Cookie": f"access_token={actor['token']}", "Origin": ORIGIN}
        search = await client.get(
            f"/api/v1/search?q=Traveller%20{other['tenant']:02d}%2000001",
            headers=headers,
        )
        if search.status_code != 200 or search.json() != []:
            raise RuntimeError("Cross-tenant search exposed a seeded foreign passenger")
        roster = await client.get(
            f"/api/v1/passports/groups/{other['group_id']}/submissions-view",
            headers=headers,
        )
        if (
            roster.status_code != 200
            or roster.json()["items"] != []
            or roster.json()["group_total"] != 0
        ):
            raise RuntimeError(
                "Cross-tenant roster boundary did not return an empty authorized set"
            )


def inspect_backend() -> dict:
    inspection = json.loads(
        subprocess.check_output(
            [*COMPOSE, "ps", "--format", "json"], cwd=ROOT, text=True
        ).splitlines()[0]
    )
    if inspection.get("Project") not in {None, "passdetection-qualification"}:
        raise RuntimeError("Unexpected Compose project")
    backend_id = subprocess.check_output(
        [*COMPOSE, "ps", "-q", "backend"], cwd=ROOT, text=True
    ).strip()
    backend = json.loads(
        subprocess.check_output(["docker", "inspect", backend_id], text=True)
    )[0]
    if (
        backend["Config"].get("Labels", {}).get("com.docker.compose.project")
        != "passdetection-qualification"
    ):
        raise RuntimeError(
            "Backend container does not belong to the isolated qualification project"
        )
    env = dict(item.split("=", 1) for item in backend["Config"]["Env"] if "=" in item)
    require_minimum_profile(
        enabled=env.get("MCP_ENABLED", "").lower() == "true",
        capabilities=json.loads(env.get("MCP_ENABLED_CAPABILITIES", "[]")),
        families=json.loads(env.get("MCP_EXPORT_FAMILIES", "[]")),
        rows=int(env.get("MCP_EXPORT_SOURCE_ROW_LIMIT", "0")),
        byte_limit=int(env.get("MCP_EXPORT_SOURCE_BYTE_LIMIT", "0")),
    )
    if (
        env.get("POSTGRES_DB") != "passdetection_ci_browser"
        or env.get("WEB_CONCURRENCY") != "4"
        or env.get("POSTGRES_API_POOL_SIZE") != "3"
        or env.get("POSTGRES_API_MAX_OVERFLOW") != "3"
        or env.get("MALWARE_SCANNER_TIMEOUT_SECONDS") != "10.0"
        or env.get("MCP_ENABLED", "").lower() != "true"
        or env.get("MCP_PUBLIC_ORIGIN") != ORIGIN
        or env.get("MCP_FRONTEND_ORIGIN") != ORIGIN
        or set(json.loads(env.get("MCP_ENABLED_CAPABILITIES", "[]"))) != {"mcp:read", "mcp:export"}
        or backend["HostConfig"]["Memory"] != API_MEMORY_BYTES
        or backend["HostConfig"]["MemorySwap"] != API_MEMORY_BYTES
        or backend["HostConfig"]["NanoCpus"] != 4 * 10**9
    ):
        raise RuntimeError(
            "Capacity lane requires its reviewed 4-worker/24-connection/2560MiB overlay"
        )
    return backend


async def main() -> int:
    run_id = uuid.uuid4().hex
    OUTPUT.mkdir(parents=True, exist_ok=True)
    backend = await asyncio.to_thread(inspect_backend)
    container_events_before = await asyncio.to_thread(capture_container_events, ROOT)
    seed = await asyncio.to_thread(fixture, "seed", run_id)
    samples = {name: [] for name in ("cold", "expected", "overload", "recovery")}
    windows = {}
    observer_path = OUTPUT / f"capacity-observer-{run_id}.jsonl"
    covers = [synthetic_jpeg(run_id, page) for page in range(8)]
    with observer_path.open("w", encoding="utf-8") as observation:
        observer = await asyncio.create_subprocess_exec(
            *FIXTURES,
            "observe",
            run_id,
            "--seconds",
            str(OBSERVATION_SECONDS),
            cwd=ROOT,
            stdout=observation,
            stderr=asyncio.subprocess.STDOUT,
        )
        async with httpx.AsyncClient(
            base_url=ORIGIN,
            verify=False,
            timeout=20,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=100),
        ) as client:
            await tenant_negatives(client, seed)
            # New run/group/user keys prove genuinely cold roster-cache reads;
            # never clear a shared Redis database to manufacture a cache miss.
            begin_stage(windows, "cold")
            for actor in seed["actors"]:
                operation, path = path_for(actor, 2)
                await measured(
                    client, samples["cold"], operation, "GET", path, actor=actor
                )
            end_stage(windows, "cold", samples["cold"])
            queued = await asyncio.to_thread(fixture, "queues", run_id)
            queues_published_at = datetime.now(UTC).isoformat()
            begin_stage(windows, "expected")
            await asyncio.gather(
                *(
                    paced_actor(
                        client, samples["expected"], actor, EXPECTED_SECONDS, index
                    )
                    for index, actor in enumerate(seed["actors"])
                ),
                scans(client, samples["expected"], seed, EXPECTED_SECONDS),
                uploads(client, samples["expected"], seed, covers),
                *(paced_reads(client, samples["expected"], actor, EXPECTED_SECONDS) for actor in seed["mcp_actors"]),
                serialized_exports(client, samples["expected"], seed["mcp_actors"], run_id, "expected"),
            )
            end_stage(windows, "expected", samples["expected"])
            overload_started = time.monotonic()
            begin_stage(windows, "overload")
            await asyncio.gather(
                *(
                    overload_actor(client, samples["overload"], seed["actors"][0])
                    for _ in range(80)
                )
            )
            overload_elapsed = time.monotonic() - overload_started
            end_stage(windows, "overload", samples["overload"])
            # Let the per-account token bucket recover naturally. No limiter
            # state is deleted and no client receives a testing bypass.
            await asyncio.sleep(4)
            recovery_started = time.monotonic()
            begin_stage(windows, "recovery")
            await asyncio.gather(
                *(
                    paced_actor(
                        client, samples["recovery"], actor, RECOVERY_SECONDS, index
                    )
                    for index, actor in enumerate(seed["actors"])
                ),
                *(paced_reads(client, samples["recovery"], actor, RECOVERY_SECONDS) for actor in seed["mcp_actors"]),
                serialized_exports(client, samples["recovery"], seed["mcp_actors"], run_id, "recovery"),
            )
            recovery_elapsed = time.monotonic() - recovery_started
            end_stage(windows, "recovery", samples["recovery"])
        try:
            jobs = await asyncio.to_thread(fixture, "verify", run_id)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError):
            # Keep the performance receipt even when durable processing fails;
            # never turn an unverified queue into a successful result.
            jobs = {
                "error": "Durable processing did not meet verification requirements"
            }
        await asyncio.wait_for(observer.wait(), timeout=180)
        if observer.returncode != 0:
            raise RuntimeError(
                "Resource observer failed; inspect its ignored local log"
            )
    metrics = []
    for line in observer_path.read_text("utf-8").splitlines():
        try:
            row = json.loads(line)
            if "database_connections" in row:
                metrics.append(row)
        except ValueError:
            continue
    stages = {name: summarize(rows) for name, rows in samples.items()}
    request_samples_path = OUTPUT / f"capacity-requests-{run_id}.jsonl"
    with request_samples_path.open("w", encoding="utf-8") as request_samples_file:
        for stage, observations in samples.items():
            for observation in observations:
                request_samples_file.write(
                    json.dumps({"stage": stage, **observation}, sort_keys=True) + "\n"
                )
    failed = gates(stages, metrics, jobs, samples, windows, queues_published_at)
    try:
        container_events_after = await asyncio.to_thread(capture_container_events, ROOT)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        container_events_after = None
    failed.extend(container_event_gates(container_events_before, container_events_after))
    receipt = {
        "container_events": {"before": container_events_before, "after": container_events_after},
        "result": "failed" if failed else "passed",
        "failed_gates": failed,
        "finished_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "image_id": backend["Image"],
        "source_revision_label": backend["Config"]["Labels"].get(
            "org.opencontainers.image.revision"
        ),
        "dataset": seed["dataset"],
        "stages": stages,
        "stage_windows": windows,
        "request_samples_file": request_samples_path.relative_to(ROOT).as_posix(),
        "slowest_requests": {
            stage: sorted(rows, key=lambda row: row["milliseconds"], reverse=True)[:10]
            for stage, rows in samples.items()
        },
        "cohort_results": {
            name: {
                cohort: summarize([row for row in rows if row["cohort"] == cohort])
                for cohort in {row["cohort"] for row in rows}
            }
            for name, rows in samples.items()
        },
        "cross_tenant_negative_checks": 40,
        "budgets_ms_p95_p99": BUDGETS_MS,
        "overload_budgets_ms_p95_p99": OVERLOAD_BUDGET_MS,
        "queue_budgets": {
            "maximum_pending_age_seconds": MAX_PENDING_AGE_SECONDS,
            "recovery_deadline_seconds": RECOVERY_DEADLINE_SECONDS,
            "queues_published_at": queues_published_at,
            "observed_drained_seconds": observed_queue_drain_seconds(
                metrics, queues_published_at
            ),
            "consecutive_empty_samples_required": 3,
        },
        "workload": {
            "expected_duration_seconds": EXPECTED_SECONDS,
            "office_requests_per_second_target": 20,
            "minimum_achieved_office_requests_per_second": 19,
            "scans_per_second_target": 1,
            "expected_scan_requests": EXPECTED_SCAN_REQUESTS,
            "expected_unique_scan_records": EXPECTED_UNIQUE_SCANS,
            "uploads_per_minute": 4,
            "upload_jpeg_bytes_each": [len(page) for page in covers],
            "distinct_upload_contents": len(set(covers)),
            "malware_scanner_timeout_seconds": 10,
            "upload_pages": 2,
            "overload_same_account_parallel_clients": 80,
            "overload_seconds": round(overload_elapsed, 3),
            "recovery_seconds": round(recovery_elapsed, 3),
            "queued_retry_burst": queued,
            "mcp_reads_per_second_target": 2,
            "mcp_minimum_reads_per_second_per_actor": 0.9,
            "mcp_verified_exports_per_stage": 2,
            "mcp_export_families": list(EXPORT_FAMILIES),
            "mcp_export_source_row_limit": SOURCE_ROWS,
            "mcp_export_source_byte_limit": SOURCE_BYTES,
            "mcp_export_scheduling": EXPORT_SCHEDULING,
            "mcp_export_rows_per_cohort": SOURCE_ROWS,
        },
        "resource_samples": metrics,
        "durable_verification": jobs,
        "limits": [
            "Synthetic local Docker environment; not a production VPS benchmark or long soak",
            "4 API workers, 24 API DB connections, 4 CPU quota and 2560MiB API memory limit",
            "General worker384MiB, ECR worker640MiB and scheduler256MiB; this is not a whole-host peak test",
            "Session fixture bypasses login; real password/MFA is qualified by the separate browser lane",
            "External AI, WhatsApp/SMTP delivery and push-provider capacity are not measured",
            "Worker burst measures durable missing-image rejection/recovery, not OCR throughput",
            "MCP sign-in is fixture-issued; real Codex, browser/MFA and OS-vault qualification remains separate",
            "MCP read/export traffic shares the website workload; this is a combined envelope, not an isolated causal overhead estimate",
            "Two MCP export journeys are serialized; planned waiting is included in unchanged export latency budgets, not concurrent-export acceptance",
        ],
        "production_changed": False,
        "existing_data_deleted": False,
    }
    destination = ROOT / "docs/implementation/mcp-workload-capacity-evidence.json"
    destination.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"result": receipt["result"], "failed_gates": failed, "stages": stages},
            indent=2,
        )
    )
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
