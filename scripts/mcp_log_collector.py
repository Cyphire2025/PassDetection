"""Operator-only, read-only source collection into exclusive sanitized diagnostic runs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.logging.mcp_log_normalization import (
    COLLECTED_SERVICES,
    WORKER_SERVICES,
    project_log_line,
)
from app.infrastructure.observability.mcp_log_reader import LOG_SOURCES
from mcp_log_binding import BindingError, DockerBinding
from mcp_log_store import (
    SourceBuffer,
    admit_output_root,
    create_run,
    seal_run,
)
from mcp_log_stream import stream_command

SOURCES_BY_SERVICE = {
    service: (
        {"api", "frontend", "integration"}
        if service == "backend"
        else {"proxy"}
        if service == "nginx"
        else {"worker", "integration"}
    )
    for service in COLLECTED_SERVICES
}


def fail(buffers: dict[str, SourceBuffer], sources: set[str], reason: str) -> None:
    for source in sources:
        buffers[source].failure = buffers[source].failure or reason


def collect_service(
    docker: DockerBinding,
    binding: Any,
    sources: dict[str, SourceBuffer],
    *,
    since: str,
    until: str,
    deadline: float,
    stream: Callable[..., Any],
) -> None:
    affected = SOURCES_BY_SERVICE[binding.service]
    # Discard the entire provisional stream if binding changed during collection.
    pending = {source: SourceBuffer() for source in LOG_SOURCES}

    def consume(line: bytes) -> None:
        projected = project_log_line(binding.service, line)
        if not projected:
            for source in affected:
                pending[source].discarded += 1
            return
        for source, record in projected.items():
            if source in affected:
                pending[source].add(record)

    try:
        docker.unchanged(binding)
        result = stream(
            docker.logs(binding, since, until),
            consume=consume,
            deadline=min(deadline, time.monotonic() + 5),
            include_stderr=True,
        )
        docker.unchanged(binding)
    except (BindingError, OSError, ValueError, TimeoutError):
        fail(sources, affected, "binding_changed")
        return
    for source in affected:
        target, captured = sources[source], pending[source]
        for line in captured.lines:
            target.add(json.loads(line))
        target.discarded += captured.discarded + result.discarded
        target.failure = target.failure or captured.failure or result.reason
        if target.discarded:
            target.failure = target.failure or "invalid_records"
        if result.reason is None:
            target.successful_services += 1


def collect(
    root: Path,
    project: str,
    output: Path,
    *,
    docker_factory: Callable[..., DockerBinding] = DockerBinding,
    stream: Callable[..., Any] = stream_command,
) -> dict[str, Any]:
    """Caller holds the root directory lock; no raw bytes are written anywhere."""
    started = datetime.now(UTC)
    deadline = time.monotonic() + 60
    since, until = (started - timedelta(minutes=15)).isoformat(), started.isoformat()
    docker = docker_factory(root, project, deadline)
    run_id = f"run-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    run = create_run(output, run_id)
    # A failed new collection remains explicitly incomplete instead of silently
    # making an older successful observation look like the newest attempt.
    bindings = docker.discover()
    sources = {source: SourceBuffer() for source in LOG_SOURCES}
    for service in ["backend", "nginx", *sorted(WORKER_SERVICES)]:
        candidates = bindings.get(service, [])
        if len(candidates) != 1:
            fail(
                sources,
                SOURCES_BY_SERVICE[service],
                "source_ambiguous" if candidates else "source_unavailable",
            )
        elif time.monotonic() >= deadline:
            fail(sources, SOURCES_BY_SERVICE[service], "collection_deadline")
        else:
            collect_service(
                docker,
                candidates[0],
                sources,
                since=since,
                until=until,
                deadline=deadline,
                stream=stream,
            )
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "collection_since": since,
        "collection_until": until,
        "coverage": "bounded_retained_tail",
        "project": project,
    }
    seal_run(output, run, manifest, sources)
    return {
        "run_id": run_id,
        "sources": {
            name: {
                "status": entry["status"],
                "reason": entry["reason"],
                "records": entry["records"],
            }
            for name, entry in manifest["sources"].items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Exact existing Compose deployment working directory",
    )
    parser.add_argument("--project", required=True, help="Exact Compose project label")
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Existing dedicated derived-log directory; never rotated or cleared",
    )
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        print('{"status":"unavailable","reason":"linux_operator_required"}')
        return 2
    import fcntl

    descriptor = None
    try:
        admit_output_root(args.output_root)
        descriptor = os.open(
            args.output_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = collect(args.root, args.project, args.output_root)
        print(json.dumps({"status": "sealed", **result}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        # Never print paths, Docker output, exceptions, or credentials on failures.
        print('{"status":"unavailable","reason":"collector_failed"}')
        return 2
    finally:
        if descriptor is not None:
            os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
