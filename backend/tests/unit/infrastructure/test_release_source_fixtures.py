"""Historical release proofs remain executable when newer revisions are added."""

import json
import shutil
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

from tests.release_source_fixtures import (
    admin_approval_source,
    dashboard_write_source,
    mcp_additive_source,
    travel_tracker_source,
)


@pytest.mark.parametrize("builder,head,kind", [
    (mcp_additive_source, "0122_mcp_gc_push", "mcp_additive_v1"),
    (admin_approval_source, "0125_mcp_connection_requests", "mcp_admin_approval_v1"),
    (dashboard_write_source, "0128_mcp_document_delivery", "mcp_dashboard_write_v1"),
    (travel_tracker_source, "0129_travel_tracker", "travel_tracker_additive_v1"),
])
def test_historical_fixture_keeps_one_complete_immutable_migration_chain(tmp_path, builder, head, kind):
    root = Path(__file__).resolve().parents[4]
    source = tmp_path / "source"
    backend = source / "backend"
    shutil.copytree(root / "backend/alembic", backend / "alembic",
                    ignore=shutil.ignore_patterns("__pycache__"))
    # A future revision must be excluded without maintaining a filename denylist.
    (backend / "alembic/versions/9999_future.py").write_text("raise AssertionError('future source loaded')")
    shutil.copy2(root / "backend/alembic.ini", backend / "alembic.ini")
    scripts = backend / "scripts"
    scripts.mkdir()
    for filename in (
        "apply_mcp_additive_upgrade.py", "apply_mcp_admin_approval_upgrade.py",
        "release_mcp_dashboard_write.py", "release_travel_tracker_upgrade.py",
        "mcp_dashboard_write_schema.py", "mcp_dashboard_write_schema.json",
    ):
        shutil.copy2(root / "backend/scripts" / filename, scripts)
    manifest = backend / "app/core/config/release_manifest.json"
    manifest.parent.mkdir(parents=True)
    shutil.copy2(root / "backend/app/core/config/release_manifest.json", manifest)

    options = {"executable": True} if builder is dashboard_write_source else {}
    result = builder(source, tmp_path / "pinned", **options)
    directory = ScriptDirectory(str(result / "backend/alembic"))
    assert directory.get_heads() == [head]
    assert list(directory.walk_revisions())[-1].down_revision is None
    assert all(int(path.name[:4]) <= int(head[:4])
               for path in (result / "backend/alembic/versions").glob("[0-9]*.py"))
    pinned_manifest = json.loads((result / "backend/app/core/config/release_manifest.json").read_text())
    assert pinned_manifest["schema_revision"] == head
    assert pinned_manifest["deployment_kind"] == kind
    for path in (result / "backend/alembic/versions").glob("*.py"):
        assert path.read_bytes() == (source / "backend/alembic/versions" / path.name).read_bytes()
