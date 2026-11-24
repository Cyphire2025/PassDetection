"""Measure HTTP contracts, timing and stage observations for the fixed QA workload."""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime

import httpx
from workload_capacity_contract import ORIGIN


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
                if actor is None:
                    valid = False
                else:
                    valid = len(body["items"]) <= 50 and body["group_total"] == actor["group_size"]
                    valid = valid and all(
                        row["group_id"] == actor["group_id"] for row in body["items"]
                    )
            elif operation == "search":
                if actor is None:
                    valid = False
                else:
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
            "request_id": response.headers.get("X-Request-ID") if response is not None else None,
            "status": status,
            "bytes": count,
            "milliseconds": (time.perf_counter() - started) * 1000,
            "valid": valid,
            "cohort": ("large_tenant" if actor["group_size"] >= 1000 else "small_tenant")
            if actor
            else "public_upload",
        }
    )
    return response


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


# Preserve the original QA import and pickle identities through its facade.
for _export in (
    percentile,
    summarize,
    measured,
    begin_stage,
    end_stage,
):
    _export.__module__ = "qualify_workload_capacity"
del _export
