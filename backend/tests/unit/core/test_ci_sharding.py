"""Exercise the CI partition contract through real pytest collection and xdist."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.ci_sharding import shard_for_nodeid

BACKEND_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def isolated_suite(tmp_path: Path) -> Path:
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    included: selected integration fixture cases\n",
        encoding="utf-8",
    )
    (tmp_path / "test_cases.py").write_text(
        """import pytest

@pytest.mark.included
@pytest.mark.parametrize("value", range(80))
def test_parameterized(value):
    assert value >= 0

@pytest.mark.parametrize("value", ["ordinary", "café", "密碼"])
def test_text(value):
    assert value

@pytest.mark.skip(reason="fixture skip")
def test_skipped():
    assert False

@pytest.mark.xfail(strict=True, reason="fixture expected failure")
def test_expected_failure():
    assert False

class TestGroup:
    def test_nested(self):
        assert True
""",
        encoding="utf-8",
    )
    (tmp_path / "conftest.py").write_text(
        """import json
import os

deselected = []

def pytest_deselected(items):
    deselected.extend(item.nodeid for item in items)

def pytest_collection_finish(session):
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    receipt = session.config.rootpath / ("collection-" + worker + ".json")
    receipt.write_text(json.dumps({
        "selected": [item.nodeid for item in session.items],
        "deselected": deselected,
    }), encoding="utf-8")
""",
        encoding="utf-8",
    )
    return tmp_path


def run_pytest(suite: Path, *args: str, hash_seed: str = "1") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTHONHASHSEED=hash_seed,
        PYTHONPATH=str(BACKEND_ROOT),
    )
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    # The fixture's child pytest is its own controller, even when this regression
    # runs inside a worker in the actual backend CI matrix.
    env.pop("PYTEST_XDIST_WORKER", None)
    env.pop("PYTEST_XDIST_WORKER_COUNT", None)
    env.pop("PYTEST_XDIST_TESTRUNUID", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests.ci_sharding", "-q", *args],
        cwd=suite,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def collection(suite: Path, *args: str, hash_seed: str = "1") -> dict[str, list[str]]:
    result = run_pytest(suite, "--collect-only", *args, hash_seed=hash_seed)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((suite / "collection-master.json").read_text(encoding="utf-8"))


def test_shards_partition_real_collection_once_in_original_order(isolated_suite: Path) -> None:
    complete = collection(isolated_suite)
    assert len(complete["selected"]) == 86
    assert complete["deselected"] == []
    owners: dict[str, int] = {}
    sizes: list[int] = []
    for index in range(1, 5):
        result = collection(isolated_suite, f"--ci-shard-index={index}", "--ci-shard-count=4")
        selected, deselected = result["selected"], result["deselected"]
        assert selected
        assert set(selected).isdisjoint(deselected)
        assert sorted(selected + deselected) == sorted(complete["selected"])
        assert selected == [nodeid for nodeid in complete["selected"] if nodeid in selected]
        for nodeid in selected:
            assert nodeid not in owners, f"{nodeid} ran in more than one shard"
            owners[nodeid] = index
        sizes.append(len(selected))
    assert set(owners) == set(complete["selected"])
    # A parameter-heavy file is partitioned at item level, not confined to one job.
    assert len({owners[nodeid] for nodeid in owners if "test_parameterized[" in nodeid}) == 4
    assert max(sizes) < 40


def test_partition_is_stable_across_python_hash_seeds(isolated_suite: Path) -> None:
    options = ("--ci-shard-index=2", "--ci-shard-count=4")
    assert collection(isolated_suite, *options, hash_seed="11") == collection(
        isolated_suite, *options, hash_seed="8675309"
    )


def test_single_shard_keeps_full_selection(isolated_suite: Path) -> None:
    assert collection(isolated_suite, "--ci-shard-index=1", "--ci-shard-count=1") == collection(
        isolated_suite
    )


def test_sharding_composes_with_pytest_filters(isolated_suite: Path) -> None:
    filters = ("-m", "included", "-k", "not 7")
    complete = collection(isolated_suite, *filters)
    assert 0 < len(complete["selected"]) < 80
    selected: list[str] = []
    for index in range(1, 5):
        result = collection(
            isolated_suite, *filters, f"--ci-shard-index={index}", "--ci-shard-count=4"
        )
        selected.extend(result["selected"])
    assert sorted(selected) == sorted(complete["selected"])


@pytest.mark.parametrize(
    "options",
    [
        ["--ci-shard-index=1"],
        ["--ci-shard-count=4"],
        ["--ci-shard-index=0", "--ci-shard-count=4"],
        ["--ci-shard-index=-1", "--ci-shard-count=4"],
        ["--ci-shard-index=5", "--ci-shard-count=4"],
        ["--ci-shard-index=1", "--ci-shard-count=0"],
        ["--ci-shard-index=1", "--ci-shard-count=-4"],
        ["--ci-shard-index=one", "--ci-shard-count=4"],
        ["--ci-shard-index=1", "--ci-shard-count=2.5"],
        ["--ci-shard-report=report.json"],
    ],
)
def test_invalid_shard_options_fail_before_collection(
    isolated_suite: Path, options: list[str]
) -> None:
    result = run_pytest(isolated_suite, "--collect-only", *options)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "ci-shard" in result.stderr
    assert not (isolated_suite / "collection-master.json").exists()


def test_xdist_workers_collect_and_execute_the_same_shard(isolated_suite: Path) -> None:
    expected = collection(isolated_suite, "--ci-shard-index=3", "--ci-shard-count=4")["selected"]
    result = run_pytest(
        isolated_suite,
        "-p",
        "xdist.plugin",
        "-n",
        "2",
        "--dist=loadfile",
        "--ci-shard-index=3",
        "--ci-shard-count=4",
        "--ci-shard-report=reports/shard.json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for worker in ("gw0", "gw1"):
        receipt = json.loads(
            (isolated_suite / f"collection-{worker}.json").read_text(encoding="utf-8")
        )
        assert receipt["selected"] == expected
    report_path = isolated_suite / "reports" / "shard.json"
    assert json.loads(report_path.read_text(encoding="utf-8"))["selected_nodeids"] == expected
    assert list(report_path.parent.iterdir()) == [report_path]
    assert "passed" in result.stdout


def test_manifest_proves_full_collection_and_selected_items(isolated_suite: Path) -> None:
    complete = collection(isolated_suite)["selected"]
    expected_hash = hashlib.sha256("\n".join(sorted(complete)).encode("utf-8")).hexdigest()
    selected = collection(
        isolated_suite,
        "--ci-shard-index=2",
        "--ci-shard-count=4",
        "--ci-shard-report=reports/shard-2.json",
    )["selected"]
    assert json.loads(
        (isolated_suite / "reports" / "shard-2.json").read_text(encoding="utf-8")
    ) == {
        "schema_version": 1,
        "shard_index": 2,
        "shard_count": 4,
        "collection_count": len(complete),
        "collection_sha256": expected_hash,
        "selected_nodeids": selected,
    }


def test_owner_is_independent_of_other_collected_items() -> None:
    nodeids = [f"tests/test_example.py::test_value[{value}]" for value in range(100)]
    owners = {nodeid: shard_for_nodeid(nodeid, 4) for nodeid in nodeids}
    assert owners == {nodeid: shard_for_nodeid(nodeid, 4) for nodeid in reversed(nodeids)}
    assert owners == {
        nodeid: shard_for_nodeid(nodeid, 4)
        for nodeid in nodeids + ["unrelated"]
        if nodeid in owners
    }
    assert all(1 <= owner <= 4 for owner in owners.values())


def test_invalid_partition_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        shard_for_nodeid("tests/test_example.py::test_value", 0)
