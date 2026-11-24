"""Prove the exact two-path scope correction and run only its tooling controls."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
REPORT = Path(__file__).resolve().parent
COHORT = "NATIVE_RESIDUAL_TEST_AND_FIXTURE_REFINEMENT"
SELECTED = (
    "backend/tests/unit/presentation/test_my_photos_dispatch_contract.py",
    "backend/tests/unit/infrastructure/fixtures/mobile_journey_london_photon.json",
)
LOOKALIKE = "backend/tests/unit/infrastructure/fixtures/mobile_journey_london_photon_extra.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


originals = json.loads((REPORT / "native-residual-two-original-sources.json").read_text())
snapshots = {row["path"]: ROOT / row["snapshot"] for row in originals["original_sources"]}
for record in originals["original_sources"]:
    assert digest(ROOT / record["snapshot"]) == record["sha256"]

policy_path = "docs/audit/dashboard-2026-10-30/audit-scope.json"
old_policy = json.loads(snapshots[policy_path].read_text())
policy = json.loads((ROOT / policy_path).read_text())
restored = copy.deepcopy(policy)
assert set(restored["native_app_only_paths"]) - set(old_policy["native_app_only_paths"]) == set(SELECTED)
assert not set(old_policy["native_app_only_paths"]) - set(restored["native_app_only_paths"])
restored["native_app_only_paths"] = [path for path in restored["native_app_only_paths"] if path not in SELECTED]
assert restored == old_policy
native = policy["native_app_only_paths"]
assert len(native) == len(set(native)) == 63
assert sum(path.startswith("backend/") for path in native) == 49
assert sum(path.startswith("backend/") and path.endswith(".py") for path in native) == 48
assert [path for path in native if path.startswith("backend/") and not path.endswith(".py")] == [SELECTED[1]]

inventory_path = "scripts/dashboard_audit_inventory.py"
old_inventory = ast.parse(snapshots[inventory_path].read_text())
inventory = ast.parse((ROOT / inventory_path).read_text())
support = next(node for node in inventory.body if isinstance(node, ast.Assign) and node.targets[0].id == "NATIVE_APP_SUPPORT_PATHS")
elements = support.value.args[0].elts
assert sum(isinstance(node, ast.Constant) and node.value == SELECTED[1] for node in elements) == 1
elements[:] = [node for node in elements if not (isinstance(node, ast.Constant) and node.value == SELECTED[1])]
assert ast.dump(inventory) == ast.dump(old_inventory)

test_path = "backend/tests/unit/scripts/test_dashboard_audit_scope.py"
old_tests = ast.parse(snapshots[test_path].read_text())
tests = ast.parse((ROOT / test_path).read_text())
cohort = next(node for node in tests.body if isinstance(node, ast.Assign) and node.targets[0].id == COHORT)
assert tuple(node.value for node in cohort.value.elts) == SELECTED
tests.body.remove(cohort)
functions = {node.name: node for node in tests.body if isinstance(node, ast.FunctionDef)}
history = functions["test_native_scope_preserves_existing_full_read_and_independent_followup"]
history_cases = history.decorator_list[0].args[1].elts
assert sum(isinstance(node, ast.Starred) and node.value.id == COHORT for node in history_cases) == 1
history_cases[:] = [node for node in history_cases if not (isinstance(node, ast.Starred) and node.value.id == COHORT)]
checked = functions["test_checked_in_native_scope_has_only_approved_literal_cohorts"]
assert checked.body[1].test.comparators[0].value == 63
assert checked.body[2].test.comparators[0].value == 49
checked.body[1].test.comparators[0].value = 61
checked.body[2].test.comparators[0].value = 47
union = checked.body[3].test.comparators[0].args[0].elts
assert sum(isinstance(node, ast.Starred) and node.value.id == COHORT for node in union) == 1
union[:] = [node for node in union if not (isinstance(node, ast.Starred) and node.value.id == COHORT)]
invalid = functions["test_invalid_native_scope_cannot_replace_inventory"]
invalid_cases = invalid.decorator_list[0].args[1].elts
lookalikes = [node for node in invalid_cases if isinstance(node, ast.List) and len(node.elts) == 1 and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == LOOKALIKE]
assert len(lookalikes) == 1
invalid_cases.remove(lookalikes[0])
assert ast.dump(tests) == ast.dump(old_tests)

equivalence = {
    "policy_inverse_all_old_values_exact": True,
    "inventory_AST_inverse_only_exact_JSON_support_literal": True,
    "test_AST_inverse_all_original_bodies_assertions_exact": True,
    "new_native_paths": list(SELECTED),
    "new_negative_policy_path": LOOKALIKE,
    "new_controls": "Two existing full/finding-history cases plus one exact-backend-JSON false-positive rejection",
    "no_other_policy_values_changed": True,
    "native_literals": 63,
    "backend_native_literals": 49,
    "backend_native_Python_literals": 48,
    "backend_native_JSON_literals": 1,
    "nonbackend_native_literals": 14,
}
dump(REPORT / "native-residual-two-equivalence.json", equivalence)

fence_paths = [policy_path, inventory_path, test_path,
    "backend/tests/unit/scripts/test_dashboard_audit_artifact_retirement.py",
    "backend/tests/unit/scripts/test_dashboard_audit_review_resolutions.py",
    "backend/pyproject.toml", *SELECTED]
before = {path: digest(ROOT / path) for path in fence_paths}
environment = dict(os.environ)
for key in list(environment):
    if key.startswith("PYTEST_") or key in {"COVERAGE_FILE", "COVERAGE_PROCESS_START"}:
        environment.pop(key)
commands = [
    ("tests", [sys.executable, "-m", "pytest", "-q", "-o", "addopts=",
        "--confcutdir=tests/unit/scripts",
        "tests/unit/scripts/test_dashboard_audit_scope.py",
        "tests/unit/scripts/test_dashboard_audit_artifact_retirement.py",
        "tests/unit/scripts/test_dashboard_audit_review_resolutions.py",
        "--junitxml=" + str(REPORT / "native-residual-two-junit.xml")]),
    ("lint", [sys.executable, "-m", "ruff", "check", "--no-fix", "--config", "pyproject.toml",
        "../scripts/dashboard_audit_inventory.py",
        "tests/unit/scripts/test_dashboard_audit_scope.py",
        "tests/unit/scripts/test_dashboard_audit_artifact_retirement.py",
        "tests/unit/scripts/test_dashboard_audit_review_resolutions.py"]),
]
results = []
for name, command in commands:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT / "backend", env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = REPORT / f"native-residual-two-{name}.txt"
    log.write_text(result.stdout + result.stderr, encoding="utf-8", newline="\n")
    results.append({"name": name, "command": command, "cwd": str(ROOT / "backend"), "exit_code": result.returncode,
        "seconds": round(time.monotonic() - started, 3), "log": log.name, "log_sha256": digest(log)})
    print(name, result.returncode, (result.stdout + result.stderr).strip(), flush=True)
    if result.returncode:
        break
after = {path: digest(ROOT / path) for path in fence_paths}
assert before == after
dump(REPORT / "native-residual-two-controls.json", {"source_fence": before, "source_fence_unchanged": before == after, "results": results,
    "limits": ["Only three audit tooling control modules; parent application conftest excluded with confcutdir.",
        "No app/native/Inbox feature test execution or provider/production access; no-fix Ruff uses explicit backend config."]})
assert len(results) == 2 and all(row["exit_code"] == 0 for row in results)
