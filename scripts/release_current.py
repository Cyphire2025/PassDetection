"""Prepare/activate the reviewed manifest with backup and all-worker gates.

Historical release helpers retain their original schemas. Use this entrypoint
for the current candidate; it never restores, downgrades, or deletes data.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from database_identity_environment import prepare_database_identity_environment
from release_manifest import (
    load_release_manifest,
    verify_rendered_release,
    verify_source_defaults,
)
from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ROOT, ReleaseError
from release_traveller_whatsapp import main as run_release
from storage_release import StorageRelease
from storage_writer_fence import recover_pending_storage_writers


class CurrentRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        manifest = load_release_manifest(root / "backend/app/core/config/release_manifest.json")
        self.release_contract = manifest
        super().__init__(
            revision, root,
            expected_schema=manifest["schema_revision"],
            previous_schema=manifest["previous_schema_revision"],
            directory_name="current-release",
            worker_nodes=manifest["worker_nodes"],
        )
        self.schema_service = "database-admin"
        self.migration_service = "database-migrate"
        self.storage = StorageRelease(self)

    def verify_running_project(self) -> dict[str, Any]:
        current = super().verify_running_project()
        self.compose.extend(["--profile", "maintenance", "-f", "docker-compose.storage-production.yml"])
        return current

    def prepare(self) -> None:
        self.verify_checkout()
        recover_pending_storage_writers(self)
        self.verify_running_project()
        # Only add missing independent identities. Bootstrap settings and all
        # existing secrets remain intact; this never restarts a live process.
        env_path = self.root / ".env"
        if not env_path.is_file() or env_path.is_symlink():
            raise ReleaseError("A protected regular production .env file is required")
        original = env_path.read_text()
        prepared = prepare_database_identity_environment(original)
        prepared = self.storage.prepare_environment(prepared)
        if prepared != original:
            backup = self.directory / f"{self.revision}.env.backup"
            if not backup.exists():
                self.write_private(backup, original, exclusive=True)
            self.write_private(env_path, prepared)
        self.storage.prepare_identity(json.loads(self.dc("config", "--format", "json")))
        super().prepare()

    def activate(self) -> None:
        self.verify_checkout()
        recover_pending_storage_writers(self)
        super().activate()

    def config_fingerprint(self, config: dict[str, Any]) -> str:
        path = Path(config["services"]["database-admin"]["environment"]["OBJECT_STORAGE_IDENTITY_FILE"])
        identity_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashlib.sha256((super().config_fingerprint(config) + identity_digest).encode()).hexdigest()

    def pinned_services(self, images: dict[str, str]) -> dict[str, dict[str, str]]:
        services = super().pinned_services(images)
        for name in ("database-admin", "database-migrate", "storage-copy"):
            services[name] = {"image": images["worker"], "pull_policy": "never"}
        return services

    def before_migration(self, current_schema: str) -> None:
        super().before_migration(current_schema)  # Verified new archive first.
        self.say("Provisioning restricted runtime and migration identities without deleting data")
        self.dc(
            "run", "--rm", "--no-deps", "database-admin", "python",
            "scripts/provision_database_roles.py", pinned=True, timeout=180,
        )
        self.storage.activate(json.loads(self.dc("config", "--format", "json")))

    def preflight(self) -> dict[str, Any]:
        verify_source_defaults(self.root)
        config = super().preflight()
        enabled = config["services"]["worker"].get("environment", {}).get("MOBILE_PUSH_APNS_ENABLED", "false")
        if str(enabled).lower() in {"true", "1"}:
            self.compose.extend(["-f", "docker-compose.apns.yml"])
            config = json.loads(self.dc("config", "--format", "json"))
        # The base helper injects the candidate revision for image preparation.
        # Also inspect the operator's real schema value so a stale .env override
        # is not silently hidden by that fixture-like injection.
        candidate_environment = self.env
        self.env = dict(candidate_environment)
        self.env.pop("EXPECTED_DATABASE_SCHEMA_REVISION", None)
        if "EXPECTED_DATABASE_SCHEMA_REVISION" in os.environ:
            self.env["EXPECTED_DATABASE_SCHEMA_REVISION"] = os.environ["EXPECTED_DATABASE_SCHEMA_REVISION"]
        try:
            actual_config = json.loads(self.dc("config", "--format", "json"))
        finally:
            self.env = candidate_environment
        verify_rendered_release(actual_config, self.release_contract)
        services = actual_config["services"]
        bootstrap = services["db"]["environment"]
        runtime = services["backend"]["environment"]
        migration = services.get("database-migrate", {}).get("environment", {})
        administrator = services.get("database-admin", {}).get("environment", {})
        if len({bootstrap.get("POSTGRES_USER"), runtime.get("POSTGRES_USER"), migration.get("POSTGRES_USER")}) != 3:
            raise ReleaseError("Bootstrap, runtime and migration identities must be distinct")
        if any(administrator.get(key) != bootstrap.get(key) for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")):
            raise ReleaseError("Maintenance identity must target the existing bootstrap database")
        if any(not runtime.get(key) for key in ("POSTGRES_USER", "POSTGRES_PASSWORD")):
            raise ReleaseError("Runtime database identity is incomplete")
        self.storage.validate(actual_config)
        return config


if __name__ == "__main__":
    raise SystemExit(run_release(CurrentRelease, description=__doc__))
