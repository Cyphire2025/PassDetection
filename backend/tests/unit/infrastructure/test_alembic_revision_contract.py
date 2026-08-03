from __future__ import annotations

import ast
from pathlib import Path


def test_all_alembic_revision_identifiers_fit_version_table() -> None:
    versions_dir = Path(__file__).resolve().parents[3] / "alembic" / "versions"
    for migration_path in versions_dir.glob("*.py"):
        module = ast.parse(migration_path.read_text(encoding="utf-8"))
        revision: str | None = None
        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "revision"
                for target in node.targets
            ):
                continue
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                revision = value
            break
        assert revision is not None, f"Missing revision in {migration_path.name}"
        assert len(revision) <= 32, (
            f"Alembic revision {revision!r} in {migration_path.name} exceeds "
            "the production alembic_version.version_num VARCHAR(32) contract"
        )
