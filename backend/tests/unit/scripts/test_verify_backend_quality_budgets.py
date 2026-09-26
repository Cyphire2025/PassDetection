from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "verify_backend_quality_budgets.py"
)
SPEC = importlib.util.spec_from_file_location("verify_backend_quality_budgets", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
quality = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = quality
SPEC.loader.exec_module(quality)


def _budget(path: str = "app/large.py") -> object:
    return quality.ModuleBudget(
        path=path,
        baseline_lines=3,
        maximum_lines=4,
        baseline_max_function_complexity=2,
        maximum_function_complexity=2,
        minimum_coverage_percent=75.0,
    )


def test_measure_source_counts_branches_deterministically(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "def choose(first, second):\n"
        "    if first and second:\n"
        "        return first\n"
        "    return second\n",
        encoding="utf-8",
    )

    result = quality.measure_source(source, "app/module.py")

    assert result.lines == 4
    assert result.max_function_complexity == 3
    assert result.most_complex_function == "choose"


def test_evaluate_budgets_rejects_size_complexity_coverage_and_untracked_module(
    tmp_path: Path,
) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "large.py").write_text(
        "def risky(a, b):\n"
        "    if a and b:\n"
        "        return 1\n"
        "    return 0\n"
        "\n",
        encoding="utf-8",
    )
    (app / "untracked.py").write_text("one = 1\ntwo = 2\nthree = 3\n", encoding="utf-8")

    _measurements, violations = quality.evaluate_budgets(
        backend_root=tmp_path,
        threshold=3,
        budgets=[_budget()],
        coverage_percentages={"app/large.py": 74.99},
    )

    assert any("unreviewed oversized module" in value for value in violations)
    assert any("lines exceeds reviewed ceiling" in value for value in violations)
    assert any("complexity 3 exceeds" in value for value in violations)
    assert any("coverage 74.99%" in value for value in violations)


def test_load_coverage_normalizes_app_source_root(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(
        "<?xml version='1.0'?>"
        "<coverage><packages><package><classes>"
        "<class filename='presentation/api.py' line-rate='0.8125'/>"
        "</classes></package></packages></coverage>",
        encoding="utf-8",
    )

    assert quality.load_coverage_percentages(coverage) == {
        "app/presentation/api.py": pytest.approx(81.25)
    }


def _coverage_gate_files(tmp_path: Path, *, measured_branches: int = 10) -> tuple[Path, Path]:
    budget = tmp_path / "budgets.json"
    budget.write_text(json.dumps({"coverage_gates": {
        "global": {"minimum_line_percent": 70, "minimum_branch_percent": 60},
        "critical_modules": [{"path": "app/security.py", "minimum_line_percent": 90, "minimum_branch_percent": 85}],
    }}), encoding="utf-8")
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(
        f'<coverage line-rate="0.80" branch-rate="0.70" branches-valid="{measured_branches}">'
        '<packages><package><classes><class filename="security.py" line-rate="0.99" branch-rate="0.80"/>'
        '</classes></package></packages></coverage>', encoding="utf-8",
    )
    return budget, coverage


def test_critical_branch_regression_fails_even_when_lines_and_global_coverage_pass(tmp_path: Path) -> None:
    budget, coverage = _coverage_gate_files(tmp_path)
    assert quality.evaluate_coverage_gates(budget, coverage) == [
        "app/security.py: branch coverage 80.00% is below reviewed floor 85.00%"
    ]


def test_statement_only_report_cannot_satisfy_branch_gate(tmp_path: Path) -> None:
    budget, coverage = _coverage_gate_files(tmp_path, measured_branches=0)
    assert quality.evaluate_coverage_gates(budget, coverage) == [
        "Branch coverage was not measured; run pytest with --cov-branch"
    ]


def test_global_regression_and_missing_critical_module_fail(tmp_path: Path) -> None:
    budget, coverage = _coverage_gate_files(tmp_path)
    coverage.write_text('<coverage line-rate="0.69" branch-rate="0.59" branches-valid="10"/>', encoding="utf-8")
    violations = quality.evaluate_coverage_gates(budget, coverage)
    assert len(violations) == 3
    assert any("Repository: line coverage" in value for value in violations)
    assert any("Repository: branch coverage" in value for value in violations)
    assert any("critical module is missing" in value for value in violations)


def test_nonfinite_coverage_floor_is_rejected(tmp_path: Path) -> None:
    budget, coverage = _coverage_gate_files(tmp_path)
    document = json.loads(budget.read_text(encoding="utf-8"))
    document["coverage_gates"]["global"]["minimum_line_percent"] = "nan"
    budget.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid line coverage floor"):
        quality.evaluate_coverage_gates(budget, coverage)
