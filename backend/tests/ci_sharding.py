"""Deterministic, opt-in partitioning for backend CI test jobs.

Run each one-based shard with the same test selection and shard count::

    pytest -p tests.ci_sharding --ci-shard-index=1 --ci-shard-count=4 -n 4 \
        --ci-shard-report=outputs/shard-1.json

Every collected node ID belongs to exactly one shard, independently of Python's
hash seed, collection order, and xdist worker. Parameterized cases are separate
items, so large test modules do not force a single shard to run all their cases.
Selection preserves pytest's collection order and reports excluded items through
the standard deselection hook. Omitting both options runs the complete selection.

Coverage must be combined from every successful shard before applying the normal
coverage floors; individual shards cannot establish whole-suite coverage.
The JSON reports describe the full collection fingerprint and selected node IDs
so a later gate can verify that all shards cover the collection exactly once.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest


def shard_for_nodeid(nodeid: str, shard_count: int) -> int:
    """Return the stable one-based owner of a collected test node ID."""
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    digest = hashlib.sha256(nodeid.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % shard_count + 1


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("ci-sharding", "Deterministic CI test partitioning")
    group.addoption(
        "--ci-shard-index",
        type=int,
        default=None,
        help="One-based shard to run; requires --ci-shard-count.",
    )
    group.addoption(
        "--ci-shard-count",
        type=int,
        default=None,
        help="Total number of shards; requires --ci-shard-index.",
    )
    group.addoption(
        "--ci-shard-report",
        type=Path,
        default=None,
        help="Write the shard's collection manifest atomically to this JSON path.",
    )


def pytest_configure(config: pytest.Config) -> None:
    shard_index = config.getoption("ci_shard_index")
    shard_count = config.getoption("ci_shard_count")
    if shard_index is None and shard_count is None:
        if config.getoption("ci_shard_report") is not None:
            raise pytest.UsageError(
                "--ci-shard-report requires --ci-shard-index and --ci-shard-count"
            )
        return
    if shard_index is None or shard_count is None:
        raise pytest.UsageError("--ci-shard-index and --ci-shard-count must be supplied together")
    if shard_count < 1 or not 1 <= shard_index <= shard_count:
        raise pytest.UsageError("CI shards require 1 <= --ci-shard-index <= --ci-shard-count")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    shard_index = config.getoption("ci_shard_index")
    shard_count = config.getoption("ci_shard_count")
    if shard_index is None or not items:
        return

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        destination = (
            selected if shard_for_nodeid(item.nodeid, shard_count) == shard_index else deselected
        )
        destination.append(item)
    report_path = config.getoption("ci_shard_report")
    if report_path is not None:
        _write_report(report_path, shard_index, shard_count, items, selected)
    items[:] = selected
    if deselected:
        config.hook.pytest_deselected(items=deselected)


def _write_report(
    path: Path,
    shard_index: int,
    shard_count: int,
    collected: list[pytest.Item],
    selected: list[pytest.Item],
) -> None:
    """All xdist workers publish identical data; readers never see partial JSON."""
    collection_ids = sorted(item.nodeid for item in collected)
    report = {
        "schema_version": 1,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "collection_count": len(collection_ids),
        "collection_sha256": hashlib.sha256("\n".join(collection_ids).encode("utf-8")).hexdigest(),
        "selected_nodeids": [item.nodeid for item in selected],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(json.dumps(report, sort_keys=True) + "\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
