"""Sealed diagnostic evidence never substitutes stale or partial files for health."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.infrastructure.observability.mcp_log_reader import LOG_SOURCES
from app.infrastructure.observability.mcp_log_runs import SealedMCPLogReader


def sealed(root, *, age=0, status="available", reason=None):
    now = datetime.now(UTC) - timedelta(seconds=age)
    name = f"run-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    run = root / name
    run.mkdir()
    record = {"timestamp": now.isoformat(), "event": "unhandled_exception", "level": "error"}
    data = (json.dumps(record) + "\n").encode()
    sources = {}
    for source in LOG_SOURCES:
        (run / f"{source}.jsonl").write_bytes(data)
        sources[source] = {
            "file": f"{source}.jsonl",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "records": 1,
            "discarded": 0,
            "input_truncated": False,
            "status": status,
            "reason": reason,
        }
    manifest = {
        "schema_version": 1,
        "run_id": name,
        "started_at": now.isoformat(),
        "finished_at": now.isoformat(),
        "collection_since": (now - timedelta(minutes=10)).isoformat(),
        "collection_until": now.isoformat(),
        "sources": sources,
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    return run, manifest


async def test_fresh_verified_run_reports_observation_window_and_records(tmp_path):
    _, manifest = sealed(tmp_path)
    result = await SealedMCPLogReader(tmp_path).read("api")
    assert result.available and len(result.records) == 1 and not result.truncated
    assert result.collector_observed_at == manifest["finished_at"]
    assert result.collector_window["since"] == manifest["collection_since"]


@pytest.mark.parametrize(
    "status,reason",
    [
        ("partial", "input_limit"),
        ("partial", "invalid_records"),
        ("unavailable", "stream_timeout"),
        ("unavailable", "source_ambiguous"),
    ],
)
async def test_partial_and_failed_collection_are_explicit(tmp_path, status, reason):
    sealed(tmp_path, status=status, reason=reason)
    result = await SealedMCPLogReader(tmp_path).read("worker")
    assert result.available == (status != "unavailable")
    assert (result.collector_reason if result.available else result.reason) == reason
    assert result.truncated == (status == "partial")


@pytest.mark.parametrize("age,reason", [(301, "collector_stale"), (-31, "collector_clock_invalid")])
async def test_stale_and_future_run_never_report_no_matches(tmp_path, age, reason):
    sealed(tmp_path, age=age)
    result = await SealedMCPLogReader(tmp_path).read("api")
    assert not result.available and result.reason == reason and not result.records


@pytest.mark.parametrize(
    "change", ["digest", "size", "count", "run_id", "path", "reason", "missing", "partial_file"]
)
async def test_manifest_and_source_integrity_fail_closed(tmp_path, change):
    run, manifest = sealed(tmp_path)
    if change == "digest":
        manifest["sources"]["api"]["sha256"] = "a" * 64
    elif change == "size":
        manifest["sources"]["api"]["size_bytes"] += 1
    elif change == "count":
        manifest["sources"]["api"]["records"] += 1
    elif change == "run_id":
        manifest["run_id"] = "run-wrong"
    elif change == "path":
        manifest["sources"]["api"]["file"] = "../SECRET"
    elif change == "reason":
        manifest["sources"]["api"]["reason"] = "SECRET_EXCEPTION"
    elif change == "missing":
        (run / "api.jsonl").rename(run / "retained-fixture.jsonl")
    else:
        (run / "api.jsonl").write_bytes(b'{"SECRET":')
    (run / "manifest.json").write_text(json.dumps(manifest))
    result = await SealedMCPLogReader(tmp_path).read("api")
    assert not result.available and result.records == () and "SECRET" not in str(result)


async def test_latest_incomplete_run_is_not_hidden_by_older_success(tmp_path):
    sealed(tmp_path, age=10)
    now = datetime.now(UTC)
    (tmp_path / f"run-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}").mkdir()
    result = await SealedMCPLogReader(tmp_path).read("api")
    assert result.reason == "collector_latest_run_incomplete"


async def test_unbounded_directory_scan_stops_without_sorting_or_fallback(tmp_path, monkeypatch):
    sealed(tmp_path)
    for i in range(3):
        (tmp_path / f"run-20200101T00000{i}Z-{i:032x}").mkdir()
    monkeypatch.setattr("app.infrastructure.observability.mcp_log_runs.MAX_RUNS", 3)
    result = await SealedMCPLogReader(tmp_path).read("api")
    assert result.reason == "collector_run_limit"


async def test_default_and_unsealed_legacy_files_are_unavailable(tmp_path):
    assert (await SealedMCPLogReader().read("api")).reason == "collector_not_configured"
    (tmp_path / "api.jsonl").write_text("{}\n")
    assert not (await SealedMCPLogReader(tmp_path).read("api")).available


async def test_same_timestamp_runs_fail_closed_instead_of_random_uuid_order(tmp_path):
    run, _ = sealed(tmp_path)
    (tmp_path / (run.name[:20] + "-" + "f" * 32)).mkdir()
    assert (await SealedMCPLogReader(tmp_path).read("api")).reason == "collector_run_order_ambiguous"


async def test_hardlinked_evidence_rejected_even_with_matching_digest(tmp_path):
    import os
    run, _ = sealed(tmp_path)
    os.link(run / "api.jsonl", tmp_path.parent / ("extra-" + uuid.uuid4().hex))
    assert (await SealedMCPLogReader(tmp_path).read("api")).reason == "unsafe_collector_file"


@pytest.mark.parametrize("change", ["boolean_version", "available_failure", "partial_without_reason"])
async def test_manifest_status_is_not_ambiguous(tmp_path, change):
    run, manifest = sealed(tmp_path)
    if change == "boolean_version":
        manifest["schema_version"] = True
    elif change == "available_failure":
        manifest["sources"]["api"]["reason"] = "stream_failed"
    else:
        manifest["sources"]["api"]["status"] = "partial"
    (run / "manifest.json").write_text(json.dumps(manifest))
    assert not (await SealedMCPLogReader(tmp_path).read("api")).available
