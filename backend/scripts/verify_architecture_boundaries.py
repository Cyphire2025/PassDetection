"""Enforce the reviewed modular-monolith dependency contract without importing the app."""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "architecture-dependencies.json"


def imports(tree: ast.AST, module: str) -> set[str]:
    result = set()
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
            result.add(base)
            # Also catch 'from app import presentation' style boundary bypasses.
            result.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return result


def violations(root: Path = ROOT, policy_path: Path = POLICY, today: date | None = None) -> list[str]:
    policy = json.loads(policy_path.read_text("utf-8"))
    if policy.get("version") != 1:
        return ["Unsupported architecture policy version"]
    failures = []
    actual: dict[str, list[str]] = {}
    for path in (root / "app").rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        if not (relative.startswith("app/domain/") or relative.startswith("app/application/")):
            continue
        tree = ast.parse(path.read_text("utf-8-sig"), filename=relative)
        module = relative[:-3].replace("/", ".")
        dependencies = imports(tree, module)
        forbidden = ("app.presentation", "fastapi", "starlette")
        if relative.startswith("app/domain/"):
            forbidden += ("app.application", "app.infrastructure", "sqlalchemy")
        for dependency in sorted(dependencies):
            if any(dependency == prefix or dependency.startswith(prefix + ".") for prefix in forbidden):
                failures.append(f"{relative}: forbidden dependency {dependency}")
        if relative.startswith("app/application/"):
            infra = sorted(value for value in dependencies if value.startswith("app.infrastructure"))
            if infra:
                actual[relative] = infra
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Name) and node.func.id == "__import__"
                    or isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                ):
                    failures.append(f"{relative}: dynamic import needs an explicit reviewed adapter")
    reviewed = policy["transaction_services"]
    for path in sorted(set(actual) | set(reviewed)):
        entry = reviewed.get(path)
        if entry is None:
            failures.append(f"{path}: infrastructure access has no reviewed transaction-service boundary")
            continue
        if not entry.get("owner") or not entry.get("reason"):
            failures.append(f"{path}: missing accountable owner or reason")
        if date.fromisoformat(entry["review_by"]) < (today or date.today()):
            failures.append(f"{path}: architecture dependency review expired")
        if actual.get(path, []) != entry["imports"]:
            failures.append(f"{path}: dependency contract changed; review exact imports, remove stale entries")
    return failures


def main() -> int:
    errors = violations()
    if errors:
        print("\n".join(errors))
        return 1
    print("Architecture boundaries verified: isolated domain; no application HTTP dependencies; "
          "only explicitly reviewed infrastructure edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
