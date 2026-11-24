"""Evaluate unchanged latency, throughput, isolation and queue acceptance gates."""

from __future__ import annotations

from datetime import datetime

from mcp_capacity import gates as mcp_gates
from workload_capacity_contract import (
    API_MEMORY_BYTES,
    BUDGETS_MS,
    EXPECTED_SCAN_REQUESTS,
    EXPECTED_UNIQUE_SCANS,
    MAX_PENDING_AGE_SECONDS,
    OBSERVED_QUEUES,
    OVERLOAD_BUDGET_MS,
    RECOVERY_DEADLINE_SECONDS,
)
from workload_capacity_measurements import summarize


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
        within = [instant for instant in observed_times if start - 4 <= instant <= end + 4]
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
            if result["contract_failures"] or result["p95_ms"] > p95 or result["p99_ms"] > p99:
                failures.append(f"{stage}:{operation}:contract_or_latency_budget")
        # Large groups must not disappear inside a pooled percentile dominated
        # by the nine smaller tenants. Apply the same existing operation floors.
        for cohort in ("large_tenant", "small_tenant"):
            cohort_results = summarize([row for row in samples[stage] if row["cohort"] == cohort])
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
    if overload["p95_ms"] > OVERLOAD_BUDGET_MS[0] or overload["p99_ms"] > OVERLOAD_BUDGET_MS[1]:
        failures.append("overload:latency_budget")
    if any(row["oldest_pending_age_seconds"] >= MAX_PENDING_AGE_SECONDS for row in metrics):
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
        row["database_connections"] > row["database_max_connections"] - 10 for row in metrics
    ):
        failures.append("database_connection_reserve")
    if metrics and max(row["backend_cgroup_memory_bytes"] for row in metrics) > API_MEMORY_BYTES:
        failures.append("backend_memory_budget")
    if job_verification.get("durable_jobs_verified") != 100:
        failures.append("durable_retry_recovery")
    scan_samples = [row for row in samples["expected"] if row["operation"] == "scan"]
    if len(scan_samples) != EXPECTED_SCAN_REQUESTS or any(not row["valid"] for row in scan_samples):
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


def observed_queue_drain_seconds(metrics: list[dict], published_at: str) -> float | None:
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
        empty = (
            row.get("pending_durable_jobs") == 0
            and isinstance(queues, dict)
            and all(name in queues and queues[name] == 0 for name in OBSERVED_QUEUES)
        )
        consecutive = consecutive + 1 if empty else 0
        if consecutive == 3:
            return round(instant - published, 3)
    return None


# Preserve the original QA import and pickle identities through its facade.
for _export in (
    gates,
    observed_queue_drain_seconds,
):
    _export.__module__ = "qualify_workload_capacity"
del _export
