"""Reproducible structural triage; candidates are not proof of unused/unsafe code."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/audit/dashboard-2026-10-30/source-metrics.json"
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".css"}
REVIEW_MARKERS = {
    "dynamic-code-execution": re.compile(r"(?<![\w.])(?:eval|exec)\s*\("),
    "embedded-server-script": re.compile(r"\.eval\s*\("),
    "pickle-deserialization": re.compile(r"\bpickle\.loads?\s*\("),
    "shell-interpreter": re.compile(r"\bshell\s*=\s*True"),
    "raw-html-rendering": re.compile(r"dangerouslySetInnerHTML|\.innerHTML\s*="),
    "browser-persistent-storage": re.compile(r"\b(?:localStorage|sessionStorage)\."),
}


def analyze() -> dict:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    added = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    files = []
    functions = []
    markers = []
    bodies: dict[str, list[dict]] = defaultdict(list)
    duplicates: dict[str, list[str]] = defaultdict(list)
    for relative in sorted(set(filter(None, tracked + added))):
        path = ROOT / relative
        if (not relative.startswith(("backend/app/", "frontend/", "mcp-connector/src/"))
            or path.suffix not in SUFFIXES or not path.is_file()
            or any(part in {"__tests__", "e2e", "tests", "public"} for part in path.parts)
            or ".test." in path.name or ".spec." in path.name):
            continue
        raw = path.read_bytes()
        source = raw.decode("utf-8-sig")
        digest = hashlib.sha256(raw).hexdigest()
        row = {"path": relative, "lines": len(source.splitlines()), "sha256": digest}
        files.append(row)
        for number, line in enumerate(source.splitlines(), 1):
            for label, pattern in REVIEW_MARKERS.items():
                if pattern.search(line):
                    markers.append({"path": relative, "line": number, "marker": label})
        if row["lines"] >= 20:
            duplicates[digest].append(relative)
        if path.suffix != ".py":
            continue
        tree = ast.parse(source, filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            function = {"path": relative, "name": node.name, "line": node.lineno, "lines": length}
            functions.append(function)
            if length < 10:
                continue
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body = body[1:]
            if len(body) < 2:
                continue
            signature = hashlib.sha256(ast.dump(ast.Module(body=body, type_ignores=[])).encode()).hexdigest()
            bodies[signature].append(function)
    return {
        "basis": "Automated structural triage only; manual caller/contract review required before changes.",
        "runtime_files_scanned": len(files),
        "files": sorted(files, key=lambda row: row["path"]),
        "largest_modules": sorted(files, key=lambda row: row["lines"], reverse=True)[:100],
        "long_python_functions": sorted((row for row in functions if row["lines"] > 100), key=lambda row: row["lines"], reverse=True),
        "identical_modules": [paths for paths in duplicates.values() if len(paths) > 1],
        "manual_review_markers": markers,
        "identical_python_function_body_candidates": [rows for rows in bodies.values() if len(rows) > 1],
    }


if __name__ == "__main__":
    result = analyze()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: len(value) if isinstance(value, list) else value for key, value in result.items() if key != "files"}, indent=2))
