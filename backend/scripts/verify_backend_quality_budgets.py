"""Enforce reviewed size, complexity, and coverage ratchets for large modules."""

from __future__ import annotations

import argparse
import ast
import json
import math
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUDGET_FILE = BACKEND_ROOT / "backend_quality_budgets.json"


@dataclass(frozen=True, slots=True)
class ModuleBudget:
    path: str
    baseline_lines: int
    maximum_lines: int
    baseline_max_function_complexity: int
    maximum_function_complexity: int
    minimum_coverage_percent: float


@dataclass(frozen=True, slots=True)
class ModuleMeasurement:
    path: str
    lines: int
    max_function_complexity: int
    most_complex_function: str | None
    coverage_percent: float | None


class _ComplexityVisitor(ast.NodeVisitor):
    """Small deterministic McCabe-style counter with no runtime dependency."""

    def __init__(self) -> None:
        self._functions: list[list[Any]] = []
        self.results: list[tuple[str, int]] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._functions.append([node.name, 1])
        self.generic_visit(node)
        name, complexity = self._functions.pop()
        self.results.append((str(name), int(complexity)))

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def _add_branch(self, node: ast.AST, count: int = 1) -> None:
        if self._functions:
            self._functions[-1][1] += count
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._add_branch(node)

    def visit_For(self, node: ast.For) -> None:
        self._add_branch(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._add_branch(node)

    def visit_While(self, node: ast.While) -> None:
        self._add_branch(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._add_branch(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._add_branch(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._add_branch(node, max(1, len(node.cases)))

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self._add_branch(node, max(0, len(node.values) - 1))

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._add_branch(node, 1 + len(node.ifs))


def _normalized_relative_path(value: str) -> str:
    normalized = str(PurePosixPath(value.replace("\\", "/")))
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"Budget path must stay inside the backend: {value!r}")
    return normalized


def load_budget_file(path: Path) -> tuple[int, list[ModuleBudget]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("backend quality budget schema_version must be 1")
    threshold = int(document["untracked_module_line_threshold"])
    if threshold < 1:
        raise ValueError("untracked_module_line_threshold must be positive")

    budgets: list[ModuleBudget] = []
    seen: set[str] = set()
    for raw in document["modules"]:
        normalized_path = _normalized_relative_path(str(raw["path"]))
        if normalized_path in seen:
            raise ValueError(f"Duplicate backend quality budget: {normalized_path}")
        seen.add(normalized_path)
        budget = ModuleBudget(
            path=normalized_path,
            baseline_lines=int(raw["baseline_lines"]),
            maximum_lines=int(raw["maximum_lines"]),
            baseline_max_function_complexity=int(
                raw["baseline_max_function_complexity"]
            ),
            maximum_function_complexity=int(raw["maximum_function_complexity"]),
            minimum_coverage_percent=float(raw["minimum_coverage_percent"]),
        )
        if budget.baseline_lines < 1 or budget.maximum_lines < budget.baseline_lines:
            raise ValueError(f"Invalid line budget for {budget.path}")
        if (
            budget.baseline_max_function_complexity < 1
            or budget.maximum_function_complexity
            < budget.baseline_max_function_complexity
        ):
            raise ValueError(f"Invalid complexity budget for {budget.path}")
        if not 0 <= budget.minimum_coverage_percent <= 100:
            raise ValueError(f"Invalid coverage floor for {budget.path}")
        budgets.append(budget)
    return threshold, budgets


def measure_source(path: Path, relative_path: str) -> ModuleMeasurement:
    source = path.read_text(encoding="utf-8")
    visitor = _ComplexityVisitor()
    visitor.visit(ast.parse(source, filename=relative_path))
    most_complex = max(visitor.results, key=lambda item: item[1], default=(None, 0))
    return ModuleMeasurement(
        path=relative_path,
        lines=len(source.splitlines()),
        max_function_complexity=most_complex[1],
        most_complex_function=most_complex[0],
        coverage_percent=None,
    )


def load_coverage_percentages(path: Path) -> dict[str, float]:
    root = ET.parse(path).getroot()
    result: dict[str, float] = {}
    for element in root.findall(".//class"):
        raw_filename = element.attrib.get("filename")
        raw_rate = element.attrib.get("line-rate")
        if raw_filename is None or raw_rate is None:
            continue
        normalized = _normalized_relative_path(raw_filename)
        app_relative = normalized if normalized.startswith("app/") else f"app/{normalized}"
        if app_relative in result:
            raise ValueError(f"Coverage report contains duplicate module: {app_relative}")
        result[app_relative] = float(raw_rate) * 100
    return result


def evaluate_coverage_gates(budget_file: Path, coverage_file: Path) -> list[str]:
    """Require measured branches and protect high-risk behavior, not just imports."""
    document = json.loads(budget_file.read_text(encoding="utf-8"))
    gates = document.get("coverage_gates")
    if gates is None:
        return []
    root = ET.parse(coverage_file).getroot()
    if int(root.attrib.get("branches-valid", "0")) <= 0:
        return ["Branch coverage was not measured; run pytest with --cov-branch"]
    modules = {}
    for element in root.findall(".//class"):
        raw_path = _normalized_relative_path(element.attrib["filename"])
        path = raw_path if raw_path.startswith("app/") else f"app/{raw_path}"
        if path in modules:
            raise ValueError(f"Coverage report contains duplicate module: {path}")
        modules[path] = element
    violations: list[str] = []

    def check(label: str, element: ET.Element, floors: dict[str, Any]) -> None:
        for metric in ("line", "branch"):
            minimum = float(floors[f"minimum_{metric}_percent"])
            observed = float(element.attrib[f"{metric}-rate"]) * 100
            if not math.isfinite(minimum) or not 0 < minimum <= 100:
                raise ValueError(f"{label}: invalid {metric} coverage floor")
            if not math.isfinite(observed) or not 0 <= observed <= 100:
                raise ValueError(f"{label}: invalid measured {metric} coverage")
            if observed + 1e-9 < minimum:
                violations.append(f"{label}: {metric} coverage {observed:.2f}% is below reviewed floor {minimum:.2f}%")

    check("Repository", root, gates["global"])
    seen: set[str] = set()
    for gate in gates["critical_modules"]:
        path = _normalized_relative_path(gate["path"])
        if path in seen:
            raise ValueError(f"Duplicate critical coverage gate: {path}")
        seen.add(path)
        if path not in modules:
            violations.append(f"{path}: critical module is missing from coverage report")
        else:
            check(path, modules[path], gate)
    return violations


def evaluate_budgets(
    *,
    backend_root: Path,
    threshold: int,
    budgets: list[ModuleBudget],
    coverage_percentages: dict[str, float] | None = None,
) -> tuple[list[ModuleMeasurement], list[str]]:
    measurements: list[ModuleMeasurement] = []
    violations: list[str] = []
    tracked_paths = {budget.path for budget in budgets}

    for source_path in sorted((backend_root / "app").rglob("*.py")):
        relative_path = source_path.relative_to(backend_root).as_posix()
        source_lines = len(source_path.read_text(encoding="utf-8").splitlines())
        if source_lines >= threshold and relative_path not in tracked_paths:
            violations.append(
                f"{relative_path}: {source_lines} lines is an unreviewed oversized module "
                f"(tracking threshold {threshold})"
            )

    for budget in budgets:
        source_path = backend_root / budget.path
        if not source_path.is_file():
            violations.append(f"{budget.path}: tracked module is missing")
            continue
        measurement = measure_source(source_path, budget.path)
        coverage_percent = (
            None
            if coverage_percentages is None
            else coverage_percentages.get(budget.path)
        )
        measurement = ModuleMeasurement(
            path=measurement.path,
            lines=measurement.lines,
            max_function_complexity=measurement.max_function_complexity,
            most_complex_function=measurement.most_complex_function,
            coverage_percent=coverage_percent,
        )
        measurements.append(measurement)
        if measurement.lines > budget.maximum_lines:
            violations.append(
                f"{budget.path}: {measurement.lines} lines exceeds reviewed ceiling "
                f"{budget.maximum_lines} (baseline {budget.baseline_lines})"
            )
        if measurement.max_function_complexity > budget.maximum_function_complexity:
            violations.append(
                f"{budget.path}:{measurement.most_complex_function}: complexity "
                f"{measurement.max_function_complexity} exceeds reviewed ceiling "
                f"{budget.maximum_function_complexity}"
            )
        if coverage_percentages is not None:
            if coverage_percent is None:
                violations.append(f"{budget.path}: module is missing from coverage report")
            elif coverage_percent + 1e-9 < budget.minimum_coverage_percent:
                violations.append(
                    f"{budget.path}: coverage {coverage_percent:.2f}% is below reviewed "
                    f"floor {budget.minimum_coverage_percent:.2f}%"
                )
    return measurements, violations


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-file", type=Path, default=DEFAULT_BUDGET_FILE)
    parser.add_argument(
        "--coverage-file",
        type=Path,
        help="Cobertura XML to activate per-module coverage floors",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        threshold, budgets = load_budget_file(args.budget_file)
        coverage = (
            load_coverage_percentages(args.coverage_file)
            if args.coverage_file is not None
            else None
        )
        _measurements, violations = evaluate_budgets(
            backend_root=BACKEND_ROOT,
            threshold=threshold,
            budgets=budgets,
            coverage_percentages=coverage,
        )
        if args.coverage_file is not None:
            violations.extend(evaluate_coverage_gates(args.budget_file, args.coverage_file))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"Backend quality budget configuration error: {exc}", file=sys.stderr)
        return 2
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(
            "Extract a cohesive module/add tests, or update the ratchet with reviewed evidence.",
            file=sys.stderr,
        )
        return 1
    coverage_note = " with coverage floors" if coverage is not None else ""
    print(f"Backend quality budgets passed ({len(budgets)} modules{coverage_note}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
