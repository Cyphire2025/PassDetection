from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_migration(filename: str) -> ModuleType:
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / filename
    )
    spec = importlib.util.spec_from_file_location(filename, migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enterprise_and_my_photos_branches_have_one_explicit_merge_head() -> None:
    my_photos = _load_migration("0086_my_photos_foundation.py")
    hardening = _load_migration("0087_enterprise_hardening.py")
    merge = _load_migration(
        "0088_merge_my_photos_and_enterprise_hardening.py"
    )

    assert my_photos.down_revision == "0085_platform_retention_controls"
    assert hardening.down_revision == "0085_platform_retention_controls"
    assert merge.revision == "0088_merge_my_photos_hardening"
    assert merge.down_revision == (
        my_photos.revision,
        hardening.revision,
    )
    assert merge.branch_labels is None
    assert merge.depends_on is None
