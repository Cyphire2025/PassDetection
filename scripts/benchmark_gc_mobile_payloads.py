"""Reproducible synthetic payload benchmark for Group Companion contracts.

This does not claim physical-device or production API latency. It compares a
representative full 1,500-passenger operational projection with the compact
manager-readiness and incremental room-change contracts used by the mobile API.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import zlib
from collections.abc import Callable
from typing import Any


def _passenger(index: int) -> dict[str, object]:
    return {
        "id": f"00000000-0000-4000-8000-{index:012d}",
        "display_name": f"Traveller {index:04d}",
        "employee_code": f"EMP-{index:05d}",
        "passport_status": "complete" if index % 47 else "needs_attention",
        "visa_status": "available" if index % 31 else "pending",
        "ticket_status": "available" if index % 19 else "pending",
        "room_number": str(400 + (index % 375)),
        "meal_preference": ("vegetarian", "standard", "vegan")[index % 3],
    }


def _compact_json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _timings(factory: Callable[[], object], iterations: int) -> dict[str, float]:
    for _ in range(5):
        _compact_json(factory())
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        _compact_json(factory())
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(samples)

    def percentile(value: float) -> float:
        position = min(len(ordered) - 1, round((len(ordered) - 1) * value))
        return ordered[position]

    return {
        "p50_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(percentile(0.95), 4),
        "p99_ms": round(percentile(0.99), 4),
    }


def _measurement(name: str, factory: Callable[[], object], iterations: int) -> dict[str, Any]:
    payload = _compact_json(factory())
    return {
        "name": name,
        "json_bytes": len(payload),
        "gzip_bytes": len(zlib.compress(payload, level=6)),
        "serialization": _timings(factory, iterations),
    }


def run(passenger_count: int, iterations: int) -> dict[str, object]:
    roster = [_passenger(index) for index in range(1, passenger_count + 1)]

    full_roster = lambda: {  # noqa: E731 - factories keep timed work explicit
        "trip_id": "10000000-0000-4000-8000-000000000001",
        "version": 42,
        "passengers": roster,
    }
    readiness = lambda: {  # noqa: E731
        "trip_id": "10000000-0000-4000-8000-000000000001",
        "passenger_count": passenger_count,
        "passports_complete": passenger_count - (passenger_count // 47),
        "visas_available": passenger_count - (passenger_count // 31),
        "tickets_available": passenger_count - (passenger_count // 19),
        "items_needing_attention": (passenger_count // 47) + (passenger_count // 31),
        "rooms_assigned": passenger_count,
        "meals_confirmed": passenger_count,
        "version": 42,
        "updated_at": "2026-08-02T12:00:00+00:00",
    }
    room_change = lambda: {  # noqa: E731
        "changes": [
            {
                "sequence": 418,
                "group_id": "10000000-0000-4000-8000-000000000001",
                "entity_type": "room_assignment",
                "entity_id": "00000000-0000-4000-8000-000000000402",
                "operation": "upsert",
                "version": 43,
                "occurred_at": "2026-08-02T12:00:00+00:00",
                "payload": {"resource_path": "/api/v1/mobile/trips/10000000-0000-4000-8000-000000000001/room"},
            }
        ],
        "next_cursor": 418,
        "has_more": False,
    }

    reference = _measurement("reference_full_roster", full_roster, iterations)
    compact = _measurement("gc_compact_readiness", readiness, iterations)
    incremental = _measurement("gc_incremental_room_change", room_change, iterations)
    readiness_reduction = 1 - compact["json_bytes"] / reference["json_bytes"]
    incremental_reduction = 1 - incremental["json_bytes"] / reference["json_bytes"]
    if readiness_reduction < 0.95 or incremental_reduction < 0.95:
        raise RuntimeError("Compact mobile contracts regressed below the 95% payload-reduction guard")

    return {
        "benchmark": "gc_mobile_payload_contracts",
        "synthetic": True,
        "passenger_count": passenger_count,
        "iterations": iterations,
        "measurements": [reference, compact, incremental],
        "comparison": {
            "readiness_json_reduction_percent": round(readiness_reduction * 100, 3),
            "room_change_json_reduction_percent": round(incremental_reduction * 100, 3),
        },
        "limitations": [
            "Payload and local JSON serialization comparison only",
            "Not a physical-device startup, rendering, network, database, or production API latency result",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--passengers", type=int, default=1_500)
    parser.add_argument("--iterations", type=int, default=101)
    arguments = parser.parse_args()
    if not 1 <= arguments.passengers <= 50_000:
        parser.error("--passengers must be between 1 and 50000")
    if not 11 <= arguments.iterations <= 10_000:
        parser.error("--iterations must be between 11 and 10000")
    print(json.dumps(run(arguments.passengers, arguments.iterations), indent=2))


if __name__ == "__main__":
    main()
