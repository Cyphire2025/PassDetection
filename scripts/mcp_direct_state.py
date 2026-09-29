"""Exclusive retained receipts and exact source/container binding for direct MCP release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

from mcp_direct_build import BuildError, command
from mcp_direct_memory import capture as capture_memory

ROOT = Path("/opt/GlobalConnectsDashboard")
PROJECT = "globalconnectsdashboard"
BASE_REVISION = "a18d236f15bd96ea326fe436cdcc28af60ec17b0"
WORKERS = {
    "worker": "general",
    "email-worker": "email",
    "email-ai-worker": "email-ai",
    "extraction-worker": "extraction",
    "verification-worker": "verification",
    "visa-ai-worker": "visa-ai",
    "my-photos-worker": "my-photos",
    "ecr-worker": "ecr",
}
APPLICATION = frozenset(WORKERS) | {"backend", "frontend", "email-beat"}
INFRASTRUCTURE = {
    "db",
    "redis",
    "redis-broker",
    "redis-realtime",
    "redis-cache",
    "minio",
    "clamav",
    "metrics-exporter",
}
SERVICES = APPLICATION | INFRASTRUCTURE | {"nginx"}


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def private_json(path: Path, value: dict) -> None:
    """An existing receipt is never truncated or replaced, including after failure."""
    descriptor = os.open(
        path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def source_inventory(source: Path) -> dict[str, str]:
    if source.is_symlink() or source.resolve() != source or not source.is_dir():
        raise BuildError("invalid_source_directory")
    result = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise BuildError("source_alias_forbidden")
        if path.is_file():
            if not stat.S_ISREG(path.stat().st_mode):
                raise BuildError("source_special_file_forbidden")
            result[path.relative_to(source).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


class DirectState:
    def __init__(self, directory: Path, revision: str):
        if not re.fullmatch("[a-f0-9]{40}", revision):
            raise BuildError("full_source_revision_required")
        if (
            directory != ROOT / "tmp" / f"mcp-direct-{revision}"
            or directory.resolve() != directory
        ):
            raise BuildError("direct_release_directory_mismatch")
        self.directory, self.revision = directory, revision
        self.source = directory / "source"
        self.journal = directory / "journal"

    def verify_source(self) -> dict:
        manifest = json.loads((self.directory / "source-manifest.json").read_text())
        if (
            manifest.get("revision") != self.revision
            or manifest.get("base_revision") != BASE_REVISION
        ):
            raise BuildError("source_identity_mismatch")
        if source_inventory(self.source) != manifest.get("files"):
            raise BuildError("source_inventory_changed")
        if hashlib.sha256(
            (self.directory / "base-requirements.lock").read_bytes()
        ).hexdigest() != manifest.get("base_requirements_sha256"):
            raise BuildError("base_requirements_changed")
        return manifest

    def event(self, phase: str, **details) -> dict:
        if not re.fullmatch("[a-z][a-z0-9_-]{0,60}", phase):
            raise BuildError("invalid_release_phase")
        self.journal.mkdir(mode=0o700, exist_ok=True)
        existing = sorted(self.journal.glob("*.json"))
        previous = (
            hashlib.sha256(existing[-1].read_bytes()).hexdigest() if existing else None
        )
        event = {
            "version": 1,
            "revision": self.revision,
            "phase": phase,
            "observed_at": datetime.now(UTC).isoformat(),
            "previous_sha256": previous,
            **details,
        }
        path = self.journal / f"{len(existing):04d}-{phase}.json"
        private_json(path, event)
        print(json.dumps({"phase": phase, "receipt": str(path)}), flush=True)
        return event

    def baseline(self) -> dict:
        self.verify_source()
        if command("git", "-C", str(ROOT), "rev-parse", "HEAD") != BASE_REVISION:
            raise BuildError("production_source_revision_changed")
        if command("git", "-C", str(ROOT), "diff", "--name-only", "HEAD"):
            raise BuildError("production_tracked_source_changed")
        ids = command("docker", "ps", "-q", "--no-trunc").split()
        rows = json.loads(command("docker", "inspect", *ids))
        selected = {}
        for item in rows:
            labels = item["Config"].get("Labels") or {}
            if labels.get("com.docker.compose.project") != PROJECT:
                continue
            service = labels.get("com.docker.compose.service")
            if (
                service not in SERVICES
                or service in selected
                or not item["State"]["Running"]
                or labels.get("com.docker.compose.project.working_dir") != str(ROOT)
                or labels.get("com.docker.compose.oneoff") != "False"
            ):
                raise BuildError("production_service_binding_changed")
            selected[service] = item
        if set(selected) != SERVICES:
            raise BuildError("production_service_inventory_incomplete")
        for service in APPLICATION - {"frontend"}:
            env = dict(
                value.split("=", 1)
                for value in selected[service]["Config"]["Env"]
                if "=" in value
            )
            if (
                env.get("APP_REVISION") != BASE_REVISION
                or env.get("EXPECTED_DATABASE_SCHEMA_REVISION")
                != "0113_document_follow_up"
            ):
                raise BuildError("production_runtime_revision_changed")
        value = {
            "revision": self.revision,
            "base_revision": BASE_REVISION,
            "containers": selected,
            "retained_container_ids": command(
                "docker", "ps", "-aq", "--no-trunc"
            ).split(),
            "source_manifest_sha256": hashlib.sha256(
                (self.directory / "source-manifest.json").read_bytes()
            ).hexdigest(),
        }
        memory = capture_memory(
            selected,
            inspect=lambda expected: json.loads(
                command("docker", "inspect", expected["Id"])
            )[0],
        )
        private_json(self.directory / "oom-prepare.private.json", memory)
        private_json(self.directory / "baseline.private.json", value)
        self.event(
            "baseline-bound",
            services={key: item["Id"] for key, item in selected.items()},
        )
        return value

    def load_baseline(self) -> dict:
        self.verify_source()
        return json.loads((self.directory / "baseline.private.json").read_text())

    def verify_retention(self, baseline: dict) -> None:
        retained = set(command("docker", "ps", "-aq", "--no-trunc").split())
        if not set(baseline["retained_container_ids"]) <= retained:
            raise BuildError("existing_container_missing")
