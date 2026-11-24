"""Verify complete, disjoint backend test-shard collection evidence."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def collection_digest(nodeids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(nodeids)).encode("utf-8")).hexdigest()


def verify_shards(directory: Path, count: int) -> None:
    reports = sorted(directory.glob("ci-shard-*.json"))
    if len(reports) != count or count < 1:
        raise ValueError("Every backend shard must supply its collection report")
    selections: list[str] = []
    indexes = set()
    collections = set()
    for path in reports:
        report = json.loads(path.read_text("utf-8"))
        index = report["shard_index"]
        if (type(index) is not int or not 1 <= index <= count or index in indexes
                or report.get("schema_version") != 1
                or report["shard_count"] != count or type(report["collection_count"]) is not int
                or report["collection_count"] < 1
                or not re.fullmatch(r"[0-9a-f]{64}", report["collection_sha256"])):
            raise ValueError("Backend shard identity or collection is inconsistent")
        selected = report["selected_nodeids"]
        if not isinstance(selected, list) or not selected or any(not isinstance(x, str) for x in selected):
            raise ValueError("Backend shard selection must contain collected test IDs")
        indexes.add(index)
        selections.extend(selected)
        collections.add((report["collection_count"], report["collection_sha256"]))
        coverage = directory / f".coverage.shard-{index}"
        if not coverage.is_file() or coverage.stat().st_size == 0:
            raise ValueError("Every backend shard must supply coverage data")
    if (len(collections) != 1 or len(set(selections)) != len(selections)
            or (len(selections), collection_digest(selections)) not in collections):
        raise ValueError("Backend shards duplicated or omitted collected tests")
    print(f"All {len(selections)} collected tests are assigned exactly once across {count} shards.")
