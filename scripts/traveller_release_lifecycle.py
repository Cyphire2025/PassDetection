"""Original constructor, extension hooks and activation workflow."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from traveller_release_contract import (
    NODE_PREFIXES,
    PREVIOUS_SCHEMA,
    PUBLIC_URL,
    READY_PROBE,
    ROOT,
    SCHEMA,
    ReleaseError,
    updated_environment,
)
from traveller_release_preparation import _ReleasePreparation


class Release(_ReleasePreparation):
    def __init__(
        self,
        revision: str,
        root: Path = ROOT,
        *,
        expected_schema: str = SCHEMA,
        previous_schema: str = PREVIOUS_SCHEMA,
        directory_name: str = "traveller-whatsapp-release",
        include_frontend: bool = True,
        preserve_release_artifacts: bool = False,
        worker_nodes: dict[str, str] | None = None,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ReleaseError("--revision must be the full 40-character pushed commit SHA")
        self.root = root.resolve()
        self.revision = revision
        if not all(
            re.fullmatch(r"[0-9]{4}_[A-Za-z0-9_]+", value)
            for value in (expected_schema, previous_schema)
        ):
            raise ReleaseError("Release schema identifiers are invalid")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", directory_name):
            raise ReleaseError("Release directory name must be one safe directory component")
        self.expected_schema = expected_schema
        self.previous_schema = previous_schema
        self.preserve_release_artifacts = preserve_release_artifacts
        self.node_prefixes = dict(NODE_PREFIXES if worker_nodes is None else worker_nodes)
        self.schema_service = "backend"
        self.migration_service = "backend"
        self.workers = (*self.node_prefixes, "email-beat")
        self.activated_services = (
            *self.workers,
            "backend",
            *(("frontend",) if include_frontend else ()),
        )
        self.env = dict(
            os.environ, APP_REVISION=revision, EXPECTED_DATABASE_SCHEMA_REVISION=expected_schema
        )
        self.directory = self.root / "tmp" / directory_name
        self.lock_directory = self.root / "tmp" / "compose-release-lock"
        self.manifest_path = self.directory / f"{revision}.json"
        self.pin_path = self.directory / f"{revision}.compose.json"
        self.phase = "preflight"
        self.compose: list[str] = []

    def prepare_recovery(self, config: dict[str, Any]) -> None:
        """Optional release-specific recovery evidence, before image tags change."""

    def before_migration(self, current_schema: str) -> None:
        """Optional release-specific backup gate, before database/environment mutation."""

    def resume_maintenance(self, config: dict[str, Any]) -> None:
        """Optional durable maintenance recovery after prepared image validation."""

    def begin_maintenance(self, config: dict[str, Any]) -> None:
        """Optional resource fence before starting any maintenance helper."""

    def complete_activation(self, config: dict[str, Any]) -> None:
        """Optional final live deployment checks before reporting verification."""

    def pinned_services(self, images: dict[str, str]) -> dict[str, dict[str, str]]:
        return {
            service: {"image": images[service], "pull_policy": "never"}
            for service in self.activated_services
        }

    def activate(self) -> None:
        self.say("Checking prepared image IDs, checkout, and unchanged production configuration")
        config = self.preflight()
        if not self.manifest_path.is_file():
            raise ReleaseError("No prepared release exists for this revision; run prepare first")
        manifest = json.loads(self.manifest_path.read_text())
        if (
            manifest.get("version") != 1
            or manifest.get("revision") != self.revision
            or manifest.get("schema") != self.expected_schema
            or manifest.get("project") != config["name"]
            or manifest.get("config_fingerprint") != self.config_fingerprint(config)
        ):
            raise ReleaseError(
                "Prepared release does not match the checkout/settings; run prepare again"
            )
        images = manifest.get("images", {})
        refs = manifest.get("references", {})
        if set(images) != set(self.activated_services) or set(refs) != set(self.activated_services):
            raise ReleaseError("Prepared image manifest is incomplete")
        for service in self.activated_services:
            if self.verify_image(refs[service], backend=service != "frontend") != images[service]:
                raise ReleaseError(f"{service}: image tag changed after prepare; run prepare again")
        self.resume_maintenance(config)
        self.say(
            f"Checking all {len(self.node_prefixes)} workers are empty for active, reserved, and scheduled tasks"
        )
        self.worker_probe(idle=True)
        self.container("email-beat")
        self.write_private(
            self.pin_path,
            json.dumps(
                {"services": self.pinned_services(images)},
                indent=2,
            )
            + "\n",
        )
        self.begin_maintenance(config)
        current_schema = self.schema()
        if current_schema not in {self.previous_schema, self.expected_schema}:
            raise ReleaseError(
                f"This release requires database revision {self.previous_schema} or {self.expected_schema}; no broader migration was attempted"
            )
        self.before_migration(current_schema)
        env_path = self.root / ".env"
        original = env_path.read_text()
        backup = self.directory / f"{self.revision}.env.backup"
        if not backup.exists():
            self.write_private(backup, original, exclusive=True)
        self.write_private(
            env_path, updated_environment(original, self.revision, self.expected_schema)
        )
        self.say(
            f"Applying additive migration {self.expected_schema} from the prepared backend image"
        )
        self.dc(
            "run",
            *(() if self.preserve_release_artifacts else ("--rm",)),
            "--no-deps",
            self.migration_service,
            "alembic",
            "upgrade",
            self.expected_schema,
            pinned=True,
            timeout=600,
            stream=True,
        )
        if self.schema() != self.expected_schema:
            raise ReleaseError(f"Migration {self.expected_schema} was not confirmed")
        # No worker is recreated on stale pre-migration idle evidence.
        self.worker_probe(idle=True)
        options = (
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--timeout",
            "60",
            "--wait",
            "--wait-timeout",
            "180",
        )
        self.say(
            f"Activating all {len(self.node_prefixes)} workers and beat before the web services"
        )
        self.dc(*options, *self.workers, pinned=True, timeout=720, stream=True)
        self.verify_containers(self.workers, images)
        for attempt in range(6):
            try:
                self.worker_probe(idle=False)
                break
            except ReleaseError:
                if attempt == 5:
                    raise
                time.sleep(5)
        self.say("Activating and verifying backend")
        self.dc(*options, "backend", pinned=True, timeout=240, stream=True)
        self.verify_containers(("backend",), images)
        self.dc("exec", "-T", "backend", "python", "-c", READY_PROBE)
        if "frontend" in self.activated_services:
            self.say("Activating and verifying frontend")
            self.dc(*options, "frontend", pinned=True, timeout=240, stream=True)
            self.verify_containers(("frontend",), images)
        self.say("Checking Nginx and public API/frontend readiness")
        self.dc("exec", "-T", "nginx", "nginx", "-t", stream=True)
        self.dc("exec", "-T", "nginx", "nginx", "-s", "reload", stream=True)
        for route in ("/api/v1/health/ready", "/"):
            status = self.run(
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-redirs",
                "5",
                "--max-time",
                "30",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                PUBLIC_URL + route,
            )
            if status != "200":
                raise ReleaseError(f"Public {route} did not return HTTP 200")
        self.verify_containers(self.activated_services, images)
        self.dc("ps", stream=True)
        self.complete_activation(config)
        worker_count = "seven" if len(self.node_prefixes) == 7 else str(len(self.node_prefixes))
        service_summary = (
            f"backend, frontend, {worker_count} workers and beat."
            if "frontend" in self.activated_services
            else f"backend, {worker_count} workers and beat; frontend unchanged."
        )
        self.say(
            f"RELEASE VERIFIED: {self.revision}; schema {self.expected_schema}; {service_summary}"
        )


Release.__module__ = "release_traveller_whatsapp"

# Keep original public method/pickle names through the stable facade.
for _name in (
    "__init__",
    "prepare_recovery",
    "before_migration",
    "resume_maintenance",
    "begin_maintenance",
    "complete_activation",
    "pinned_services",
    "activate",
):
    _member = vars(Release)[_name]
    _function = _member.__func__ if isinstance(_member, staticmethod) else _member
    _function.__module__ = "release_traveller_whatsapp"
    _function.__qualname__ = "Release." + _name
del _name, _member, _function
