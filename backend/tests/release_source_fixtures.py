"""Pin historical release sources without weakening their exact-head guards."""

import json
import shutil
from pathlib import Path


def dashboard_write_source(source: Path, destination: Path, *, executable: bool = False) -> Path:
    """Keep 0125→0128 qualification valid after a newer additive release exists."""
    backend = destination / "backend"
    if executable:
        shutil.copytree(
            source / "backend/app", backend / "app", ignore=shutil.ignore_patterns("__pycache__")
        )
        shutil.copytree(
            source / "backend/alembic",
            backend / "alembic",
            ignore=shutil.ignore_patterns("__pycache__", "0129_travel_tracker.py"),
        )
        shutil.copy2(source / "backend/alembic.ini", backend / "alembic.ini")
    else:
        migrations = backend / "alembic/versions"
        migrations.mkdir(parents=True)
        for revision in (
            "0126_mcp_section_permissions",
            "0127_mcp_native_transfers",
            "0128_mcp_document_delivery",
        ):
            shutil.copy2(source / f"backend/alembic/versions/{revision}.py", migrations)
    scripts = backend / "scripts"
    scripts.mkdir(parents=True)
    for filename in (
        "release_mcp_dashboard_write.py",
        "mcp_dashboard_write_schema.py",
        "mcp_dashboard_write_schema.json",
    ):
        shutil.copy2(source / "backend/scripts" / filename, scripts)
    manifest = backend / "app/core/config/release_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    value = json.loads(
        (source / "backend/app/core/config/release_manifest.json").read_text("utf-8")
    )
    value.update(
        deployment_kind="mcp_dashboard_write_v1",
        previous_schema_revision="0125_mcp_connection_requests",
        schema_revision="0128_mcp_document_delivery",
    )
    manifest.write_text(json.dumps(value), encoding="utf-8")
    return destination
