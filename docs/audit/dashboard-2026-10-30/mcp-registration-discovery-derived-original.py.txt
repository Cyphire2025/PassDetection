"""Discover application workflow surfaces without importing the application.

The checked-in matrix is a review ledger, not an MCP tool allowlist. Discovery
never classifies new operations automatically: --check fails until a reviewer
adds a disposition, business workflow and evidence state. Runtime adapters must
enforce authorization and effects independently.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX = Path("docs/implementation/mcp-workflow-coverage.json")
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
DISPOSITIONS = {"implement", "internal_dependency", "manual_removal", "server_control"}
STATUSES = {"planned", "implemented_unverified", "verified", "not_applicable"}


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def literal(node: ast.expr | None, default: Any = None) -> Any:
    if node is None:
        return default
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return default


def keyword(call: ast.Call, name: str, default: Any = None) -> Any:
    return next((literal(item.value, default) for item in call.keywords if item.arg == name), default)


def discover_source_routes(root: Path) -> list[dict[str, Any]]:
    """Inventory all declared routes, including hidden and currently unmounted ones.

    IDs intentionally use the source handler and local path, independent of an
    OpenAPI export. Router registration source is also fingerprinted separately,
    so mounting/prefix changes cannot slip through the classification gate.
    """
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "backend/app").rglob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        relative = path.relative_to(root).as_posix()
        registrations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "APIRouter":
                registrations.append(ast.dump(node, include_attributes=False))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"include_router", "add_api_route", "add_route", "mount"}:
                    registrations.append(ast.dump(node, include_attributes=False))
                if node.func.attr == "extend" and ast.unparse(node.func.value).endswith(".routes"):
                    registrations.append(ast.dump(node, include_attributes=False))
            if isinstance(node, ast.For) and any(
                isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                and child.func.attr == "extend" and ast.unparse(child.func.value).endswith(".routes")
                for child in ast.walk(node)
            ):
                registrations.append(ast.dump(node, include_attributes=False))
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr
                if method == "tool":
                    rows.append({
                        "id": f"mcp_tool:{relative}:{node.name}", "kind": "mcp_tool",
                        "source": relative, "handler": node.name,
                        "contract_sha256": fingerprint(ast.dump(node.args, include_attributes=False)
                                                       + ast.dump(decorator, include_attributes=False)),
                    })
                    continue
                if method not in HTTP_METHODS | {"websocket", "api_route"}:
                    continue
                local_path = literal(decorator.args[0]) if decorator.args else keyword(decorator, "path")
                if not isinstance(local_path, str):
                    raise TypeError(f"Unresolved route path: {relative}:{node.name}")
                methods = keyword(decorator, "methods", ["GET"]) if method == "api_route" else [method.upper()]
                signature = ast.dump(node.args, include_attributes=False)
                signature += ast.dump(decorator, include_attributes=False)
                for verb in methods:
                    rows.append({
                        "id": f"route:{relative}:{node.name}:{verb}:{local_path}",
                        "kind": "source_route", "source": relative,
                        "handler": node.name, "method": verb, "local_path": local_path,
                        "contract_sha256": fingerprint(signature),
                        "summary": keyword(decorator, "summary", node.name.replace("_", " ")),
                        "schema_visible": keyword(decorator, "include_in_schema", True),
                    })
        if registrations:
            rows.append({
                "id": f"registration:{relative}", "kind": "route_registration",
                "source": relative, "contract_sha256": fingerprint("\n".join(sorted(registrations))),
            })
    return rows


def discover_openapi(root: Path) -> list[dict[str, Any]]:
    document = json.loads((root / "backend/contracts/api.openapi.json").read_text(encoding="utf-8"))
    rows = []
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            rows.append({
                "id": f"openapi:{method.upper()}:{path}", "kind": "openapi_operation",
                "source": "backend/contracts/api.openapi.json", "method": method.upper(),
                "path": path, "operation_id": operation.get("operationId"),
                "tags": operation.get("tags", []), "summary": operation.get("summary", ""),
            })
    return rows


def discover_frontend(root: Path) -> list[dict[str, Any]]:
    rows = []
    frontend = root / "frontend"
    paths = [path for directory in ("app", "features", "hooks", "lib", "components")
             for path in (frontend / directory).rglob("*.ts*")]
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(frontend).parts
        if parts[0] not in {"app", "features", "hooks", "lib", "components"}:
            continue
        if any(part in {"node_modules", ".next"} for part in parts) or re.search(r"\.(test|spec|contract)\.", path.name):
            continue
        if path.name == "page.tsx":
            rows.append({"id": f"page:{relative}", "kind": "frontend_page", "source": relative})
        # Legacy UI copy can contain Windows-1252 punctuation. Declaration
        # identifiers are ASCII; these bytes cannot add/remove an action name.
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        # Include API facade actions and exported hook/component workflows that
        # call the transport directly. Type declarations do not count as actions.
        uses_transport = "apiClient." in source or re.search(r"\bfetch\s*\(", source) is not None
        if not ("/api/" in relative or uses_transport):
            continue
        declarations = set(re.findall(r"export\s+(?:async\s+)?function\s+(\w+)\s*[(<]", source))
        declarations.update(re.findall(r"^\s{2}(\w+)\s*:\s*async\s*[(<]", source, re.MULTILINE))
        declarations.update(re.findall(r"export\s+const\s+(\w+)\s*=\s*(?:async\s*)?\(", source))
        declarations.update(re.findall(r"^\s{2}async\s+(\w+)\s*[(<]", source, re.MULTILINE))
        for declaration in sorted(declarations):
            rows.append({"id": f"frontend:{relative}:{declaration}", "kind": "frontend_callable", "source": relative, "handler": declaration})
        if "/api/" in relative and uses_transport:
            # Full facade fingerprints also cover non-async methods, aliases and
            # future TS declaration styles not recognized by the name index.
            rows.append({"id": f"frontend_api:{relative}", "kind": "frontend_api_contract", "source": relative, "contract_sha256": fingerprint(source.replace("\r\n", "\n"))})
        if path.name == "endpoints.ts":
            rows.append({"id": f"endpoint_registry:{relative}", "kind": "frontend_endpoint_registry", "source": relative, "contract_sha256": fingerprint(source.replace("\r\n", "\n"))})
    return rows


def discover(root: Path) -> list[dict[str, Any]]:
    rows = discover_source_routes(root) + discover_openapi(root) + discover_frontend(root)
    identifiers = [row["id"] for row in rows]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate workflow identifiers discovered")
    return sorted(rows, key=lambda row: row["id"])


def validate(matrix: dict[str, Any], discovered: list[dict[str, Any]], root: Path) -> list[str]:
    errors: list[str] = []
    if matrix.get("schema_version") != 1:
        errors.append("Unsupported matrix schema_version")
    reviewed = matrix.get("surfaces", [])
    indexed = {row.get("surface", {}).get("id"): row for row in reviewed}
    if len(indexed) != len(reviewed):
        errors.append("Duplicate reviewed surface IDs")
    current = {row["id"]: row for row in discovered}
    for identifier in sorted(current.keys() - indexed.keys()):
        errors.append(f"Unclassified workflow surface: {identifier}")
    for identifier in sorted(indexed.keys() - current.keys()):
        errors.append(f"Stale workflow surface: {identifier}")
    for identifier in sorted(current.keys() & indexed.keys()):
        row = indexed[identifier]
        if row["surface"] != current[identifier]:
            errors.append(f"Workflow contract changed; review classification: {identifier}")
        disposition = row.get("disposition")
        if disposition not in DISPOSITIONS:
            errors.append(f"Invalid disposition: {identifier}")
        if not row.get("workflow") or not row.get("rationale"):
            errors.append(f"Missing workflow/rationale: {identifier}")
        status = row.get("implementation", {}).get("status")
        if status not in STATUSES:
            errors.append(f"Invalid implementation status: {identifier}")
        if disposition == "implement" and (status == "not_applicable" or row.get("phase") not in range(2, 9)):
            errors.append(f"Allowed workflow needs a phase and implementation state: {identifier}")
        if disposition in {"manual_removal", "server_control"} and row.get("exclusion_boundary") not in {"no_removal", "no_server_control"}:
            errors.append(f"Exclusion lacks agreed boundary: {identifier}")
        if status == "verified":
            evidence = row.get("implementation", {}).get("evidence", [])
            if not evidence or any(
                not (root / entry).resolve().is_relative_to(root.resolve())
                or not (root / entry).is_file() for entry in evidence
            ):
                errors.append(f"Verified workflow lacks retained evidence: {identifier}")
            if not row.get("implementation", {}).get("adapter"):
                errors.append(f"Verified workflow lacks concrete adapter: {identifier}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="Reject new, changed, removed or unclassified surfaces")
    parser.add_argument("--output", type=Path, help="Write discovery only; never changes reviewed classifications")
    arguments = parser.parse_args()
    rows = discover(arguments.root)
    if arguments.output:
        arguments.output.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    if arguments.check:
        matrix = json.loads((arguments.root / MATRIX).read_text(encoding="utf-8"))
        errors = validate(matrix, rows, arguments.root)
        if errors:
            print("\n".join(errors))
            return 1
    counts = {kind: sum(row["kind"] == kind for row in rows) for kind in sorted({row["kind"] for row in rows})}
    print(json.dumps({"surfaces": len(rows), "kinds": counts, "classification_check": "passed" if arguments.check else "not_run"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
