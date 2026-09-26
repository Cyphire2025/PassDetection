"""Read the reviewed release contract without importing application settings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "backend/app/core/config/release_manifest.json"


def load_release_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("Unsupported release manifest")
    for key in ("schema_revision", "previous_schema_revision"):
        if not re.fullmatch(r"[0-9]{4}_[A-Za-z0-9_]{1,27}", manifest.get(key, "")):
            raise ValueError(f"Invalid release manifest {key}")
    nodes = manifest.get("worker_nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise ValueError("Release manifest must declare worker nodes")
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", value)
        for value in (*nodes, *nodes.values())
    ):
        raise ValueError("Invalid release worker identity")
    if len(set(nodes.values())) != len(nodes):
        raise ValueError("Worker node prefixes must be distinct")
    return manifest


def verify_rendered_release(config: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Inspect actual rendered values; never replace stale values with fixtures."""
    services = config.get("services", {})
    for name in (*manifest["worker_nodes"], "email-beat", "backend"):
        service = services.get(name)
        if not isinstance(service, dict):
            raise ValueError(f"Missing release service: {name}")
        environment = service.get("environment", {})
        if environment.get("EXPECTED_DATABASE_SCHEMA_REVISION") != manifest["schema_revision"]:
            raise ValueError(f"{name}: configured schema disagrees with reviewed release manifest")
    for name, prefix in manifest["worker_nodes"].items():
        command = services[name].get("command", [])
        rendered = command if isinstance(command, str) else " ".join(map(str, command))
        if f"{prefix}@" not in rendered:
            raise ValueError(f"{name}: worker node prefix disagrees with release manifest")


def verify_source_defaults(root: Path = ROOT) -> None:
    manifest = load_release_manifest(root / "backend/app/core/config/release_manifest.json")
    schema = manifest["schema_revision"]
    expected = {
        ".env.example": f"EXPECTED_DATABASE_SCHEMA_REVISION={schema}",
        "docker-compose.yml": f"EXPECTED_DATABASE_SCHEMA_REVISION: ${{EXPECTED_DATABASE_SCHEMA_REVISION:-{schema}}}",
    }
    for filename, declaration in expected.items():
        if declaration not in (root / filename).read_text(encoding="utf-8"):
            raise ValueError(f"{filename}: schema default differs from release manifest")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rendered-config", type=Path)
    args = parser.parse_args()
    verify_source_defaults()
    if args.rendered_config:
        verify_rendered_release(
            json.loads(args.rendered_config.read_text(encoding="utf-8")), load_release_manifest()
        )
    print("Release contract verified" + (" against actual rendered configuration" if args.rendered_config else " (source defaults only)"))
