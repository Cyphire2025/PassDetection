"""Resolve only explicit source bindings for literal route registrations.

This is static discovery, never module import or a Python evaluator. Unknown or
conditional rebinding and cycles require review instead of losing a live route.
"""

from __future__ import annotations

import ast
from pathlib import Path

Function = ast.FunctionDef | ast.AsyncFunctionDef


class _Bindings(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)  # Function-local bindings are not module bindings.

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)


def _relative_source(root: Path, path: Path, node: ast.ImportFrom) -> Path:
    if not node.level or node.module is None:
        raise TypeError("Literal route handlers require explicit relative imports")
    package = list(path.relative_to(root / "backend").parts[:-1])
    if node.level > len(package):
        raise TypeError("Route handler import escapes its package")
    parts = package[: len(package) - node.level + 1] + node.module.split(".")
    module = root / "backend" / Path(*parts)
    candidates = [
        candidate
        for candidate in [module.with_suffix(".py"), module / "__init__.py"]
        if candidate.is_file()
    ]
    if len(candidates) != 1:
        raise TypeError("Unresolved or ambiguous route handler source")
    return candidates[0]


def resolve_route_handler(
    root: Path,
    path: Path,
    name: str,
    before: int | None = None,
    seen: frozenset[tuple[str, str, int | None]] = frozenset(),
) -> tuple[Path, Function]:
    """Resolve the binding immediately before a module statement, not at EOF."""
    root = root.resolve()
    path = path.resolve()
    if not path.is_relative_to((root / "backend/app").resolve()):
        raise TypeError("Route handler source is outside the application")
    key = (str(path), name, before)
    if key in seen or len(seen) >= 16:
        raise TypeError("Cyclic or excessive route handler aliases")
    seen = seen | {key}
    statements = ast.parse(path.read_text("utf-8-sig")).body
    binding: ast.AST | None = None
    binding_position = 0
    for position, node in enumerate(statements):
        if before is not None and position >= before:
            break
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            binding = node
        elif isinstance(node, ast.ImportFrom) and any(
            alias.name == "*" or (alias.asname or alias.name) == name for alias in node.names
        ):
            binding = node
        else:
            assigned = _Bindings()
            assigned.visit(node)
            if name in assigned.names or "*" in assigned.names:
                binding = node
        if binding is node:
            binding_position = position
    if isinstance(binding, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return path, binding
    if isinstance(binding, ast.ImportFrom):
        aliases = [
            alias
            for alias in binding.names
            if alias.name != "*" and (alias.asname or alias.name) == name
        ]
        if len(aliases) != 1:
            raise TypeError("Wildcard or ambiguous route handler import")
        return resolve_route_handler(
            root, _relative_source(root, path, binding), aliases[0].name, seen=seen
        )
    if (
        isinstance(binding, ast.Assign)
        and len(binding.targets) == 1
        and isinstance(binding.targets[0], ast.Name)
    ):
        value = binding.value
        if isinstance(value, ast.Name):
            return resolve_route_handler(root, path, value.id, binding_position, seen)
        # FastAPI's literal decorator application returns the same handler.
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Call)
            and isinstance(value.func.func, ast.Attribute)
            and value.func.func.attr
            in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "head",
                "options",
                "websocket",
                "api_route",
            }
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Name)
            and value.args[0].id == name
            and not value.keywords
        ):
            return resolve_route_handler(root, path, name, binding_position, seen)
    raise TypeError(f"Unresolved or conditional route handler binding: {name}")
