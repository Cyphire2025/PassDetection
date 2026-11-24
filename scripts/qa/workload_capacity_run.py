"""Own one fixed workload run, from isolated setup through retained evidence."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from capacity_container_events import capture as capture_container_events
from capacity_container_events import gates as container_event_gates
from capacity_observer_lifecycle import finish_observer
from mcp_capacity import paced_reads, serialized_exports
from mcp_capacity_profile import EXPORT_FAMILIES, EXPORT_SCHEDULING, SOURCE_BYTES, SOURCE_ROWS
from run_qualification_stack import OUTPUT, ROOT
from workload_capacity_contract import (
    BUDGETS_MS,
    EXPECTED_SCAN_REQUESTS,
    EXPECTED_SECONDS,
    EXPECTED_UNIQUE_SCANS,
    FIXTURES,
    MAX_PENDING_AGE_SECONDS,
    OBSERVATION_SECONDS,
    ORIGIN,
    OVERLOAD_BUDGET_MS,
    RECOVERY_DEADLINE_SECONDS,
    RECOVERY_SECONDS,
)
from workload_capacity_gates import gates, observed_queue_drain_seconds
from workload_capacity_measurements import begin_stage, end_stage, measured, summarize
from workload_capacity_resources import fixture, inspect_backend
from workload_capacity_traffic import (
    overload_actor,
    paced_actor,
    path_for,
    scans,
    synthetic_jpeg,
    tenant_negatives,
    uploads,
)


async def main() -> int:
    run_id = uuid.uuid4().hex
    OUTPUT.mkdir(parents=True, exist_ok=True)
    backend = await asyncio.to_thread(inspect_backend)
    container_events_before = await asyncio.to_thread(capture_container_events, ROOT)
    seed = await asyncio.to_thread(fixture, "seed", run_id)
    samples: dict[str, list[dict[str, Any]]] = {
        name: [] for name in ("cold", "expected", "overload", "recovery")
    }
    windows: dict[str, dict[str, Any]] = {}
    observer_path = OUTPUT / f"capacity-observer-{run_id}.jsonl"
    covers = [synthetic_jpeg(run_id, page) for page in range(8)]
    with observer_path.open("w", encoding="utf-8") as observer_output:
        observer = await asyncio.create_subprocess_exec(
            *FIXTURES,
            "observe",
            run_id,
            "--seconds",
            str(OBSERVATION_SECONDS),
            cwd=ROOT,
            stdout=observer_output,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
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
                    await measured(client, samples["cold"], operation, "GET", path, actor=actor)
                end_stage(windows, "cold", samples["cold"])
                queued = await asyncio.to_thread(fixture, "queues", run_id)
                queues_published_at = datetime.now(UTC).isoformat()
                begin_stage(windows, "expected")
                await asyncio.gather(
                    *(
                        paced_actor(client, samples["expected"], actor, EXPECTED_SECONDS, index)
                        for index, actor in enumerate(seed["actors"])
                    ),
                    scans(client, samples["expected"], seed, EXPECTED_SECONDS),
                    uploads(client, samples["expected"], seed, covers),
                    *(
                        paced_reads(client, samples["expected"], actor, EXPECTED_SECONDS)
                        for actor in seed["mcp_actors"]
                    ),
                    serialized_exports(
                        client, samples["expected"], seed["mcp_actors"], run_id, "expected"
                    ),
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
                        paced_actor(client, samples["recovery"], actor, RECOVERY_SECONDS, index)
                        for index, actor in enumerate(seed["actors"])
                    ),
                    *(
                        paced_reads(client, samples["recovery"], actor, RECOVERY_SECONDS)
                        for actor in seed["mcp_actors"]
                    ),
                    serialized_exports(
                        client, samples["recovery"], seed["mcp_actors"], run_id, "recovery"
                    ),
                )
                recovery_elapsed = time.monotonic() - recovery_started
                end_stage(windows, "recovery", samples["recovery"])
            try:
                jobs = await asyncio.to_thread(fixture, "verify", run_id)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError):
                # Keep the performance receipt even when durable processing fails;
                # never turn an unverified queue into a successful result.
                jobs = {"error": "Durable processing did not meet verification requirements"}
            await asyncio.wait_for(observer.wait(), timeout=180)
            if observer.returncode != 0:
                raise RuntimeError("Resource observer failed; inspect its ignored local log")
        finally:
            await finish_observer(observer)
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
            "observed_drained_seconds": observed_queue_drain_seconds(metrics, queues_published_at),
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


main.__module__ = "qualify_workload_capacity"
