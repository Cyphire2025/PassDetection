"""Prepare/activate the reviewed manifest with backup and all-worker gates.

Historical release helpers retain their original schemas. Use this entrypoint
for the current candidate; it never restores, downgrades, or deletes data.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from database_identity_environment import prepare_database_identity_environment
from image_runtime_policy import validate_process_isolation
from release_artifacts import verify_manifest
from release_manifest import (
    load_release_manifest,
    verify_rendered_release,
    verify_source_defaults,
)
from release_reliability import ReliabilityRelease
from release_resource_fence import ResourceFence
from release_resource_profile import validate_local_swap_free_host, validate_profile
from release_traveller_whatsapp import (
    CONTROL_PROBE,
    PROBE_MARKER,
    PROJECT_LABEL,
    ROOT,
    SERVICE_LABEL,
    ReleaseError,
    validate_worker_probe,
)
from release_traveller_whatsapp import main as run_release
from storage_release import StorageRelease
from storage_writer_fence import recover_pending_storage_writers
from verify_database_deployment_budget import calculate as calculate_database_budget
from verify_deployment_resource_budget import _memory_bytes


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
            preserve_release_artifacts=True,
        )
        self.schema_service = "database-admin"
        self.migration_service = "database-migrate"
        self.storage = StorageRelease(self)
        self.resources = ResourceFence(self)
        self.resource_config: dict[str, Any] | None = None
        self.activating_release = False

    def container(self, service: str) -> dict[str, Any]:
        fenced = self.resources.container(service)
        return fenced if fenced is not None else super().container(service)

    def dc(self, *args: str, pinned: bool = False, **kwargs: Any) -> str:
        if args and self.resources.active() and self.resource_config is not None:
            starting = set(args) & {"database-admin", "database-migrate", "storage-copy", "storage-stage", "db", "clamav"}
            if args[0] in {"run", "up"} and starting:
                self.resources.admit(self.resource_config, starting)
            if args[0] == "up" and set(args) & set(self.activated_services):
                self.resources.admit_application_start(self.resource_config, set(args) & set(self.activated_services))
                self.resources.start_activation()
        return super().dc(*args, pinned=pinned, **kwargs)

    def probe_running_workers_idle(self) -> None:
        running = {name: self.resources.existing(name) for name in self.node_prefixes}
        running = {name: item for name, item in running.items() if item["State"].get("Running")}
        if not running:
            raise ReleaseError("No running worker is available for the drain probe")
        nodes = {f"{self.node_prefixes[name]}@{item['Config']['Hostname']}" for name, item in running.items()}
        output = self.run("docker", "exec", next(iter(running.values()))["Id"], "python", "-c",
                          CONTROL_PROBE, json.dumps(sorted(nodes)), "idle", timeout=55)
        payloads = [line[len(PROBE_MARKER):] for line in output.splitlines() if line.startswith(PROBE_MARKER)]
        if len(payloads) != 1:
            raise ReleaseError("Current running-worker drain probe did not return one result")
        validate_worker_probe(json.loads(payloads[0]), nodes, idle=True, expected_count=len(nodes))

    def worker_probe(self, *, idle: bool) -> None:
        if idle and self.resources.active():
            self.resources.assert_stopped()
        else:
            super().worker_probe(idle=idle)

    def verify_containers(self, services: tuple[str, ...], images: dict[str, str]) -> None:
        super().verify_containers(services, images)
        for service in services:
            if not self.container(service).get("State", {}).get("Running"):
                raise ReleaseError(f"{service}: prepared container is stopped; activation is not verified")

    def schema(self) -> str:
        # Read through the existing PostgreSQL process: no extra 512 MiB helper
        # can be admitted while the previous deployment is still running.
        return self.resources.schema()

    def resume_maintenance(self, config: dict[str, Any]) -> None:
        if self.resources.active():
            self.resources.begin(config)

    def begin_maintenance(self, config: dict[str, Any]) -> None:
        self.resources.begin(config)

    def verify_running_project(self) -> dict[str, Any]:
        checkpoint = self.resources.load()
        recovering = bool(checkpoint and checkpoint["phase"] != "complete")
        if recovering:
            assert checkpoint is not None
            project = checkpoint["project"]
            self.compose = ["docker", "compose", "-p", project, "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
                            "--profile", "maintenance", "-f", "docker-compose.storage-production.yml"]
            current = self.resources.checked_writer("backend", checkpoint)
            current = self.resources.container("backend") or current
            requested_project = self.env.get("COMPOSE_PROJECT_NAME")
            if requested_project and requested_project != project:
                raise ReleaseError("COMPOSE_PROJECT_NAME differs from the retained maintenance project")
            self._resource_overlay()
            self._verify_live_database_target(current, self.container("db"))
            return current
        identifiers = self.run("docker", "ps", "--quiet", "--filter", f"label={SERVICE_LABEL}=backend").splitlines()
        matches = []
        for identifier in identifiers:
            current = self.inspect(identifier)
            labels = current.get("Config", {}).get("Labels") or {}
            working_dir = labels.get("com.docker.compose.project.working_dir")
            if working_dir and Path(working_dir).resolve() == self.root and labels.get(SERVICE_LABEL) == "backend":
                matches.append(current)
        if len(matches) != 1:
            raise ReleaseError("Exactly one running backend in this Compose working directory is required; ambiguous or replicated deployments need a separately qualified release plan")
        current = matches[0]
        labels = current["Config"]["Labels"]
        project = labels.get(PROJECT_LABEL)
        if not project or not current.get("State", {}).get("Running"):
            raise ReleaseError("Existing backend must be running with its original Compose project labels")
        requested_project = self.env.get("COMPOSE_PROJECT_NAME")
        if requested_project and requested_project != project:
            raise ReleaseError("COMPOSE_PROJECT_NAME differs from the existing project; refusing to redirect persistent volumes")
        self.compose = ["docker", "compose", "-p", project, "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
                        "--profile", "maintenance", "-f", "docker-compose.storage-production.yml"]
        self._resource_overlay()
        self._verify_live_database_target(current, self.container("db"))
        return current

    def _resource_overlay(self) -> None:
        profile = self.env.get("RELEASE_RESOURCE_PROFILE", "")
        if profile and profile != "kvm4":
            raise ReleaseError("Unreviewed release resource profile")
        if profile == "kvm4":
            self.compose.extend(["-f", "docker-compose.kvm4.yml"])

    def prepare(self) -> None:
        self.verify_checkout()
        if self.resources.active():
            raise ReleaseError("Maintenance is already fenced; retry the same prepared activate command, not prepare")
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
        self.activating_release = True
        self.verify_promoted_release()
        self.verify_checkout()
        self.verify_resource_host()
        checkpoint = self.resources.load()
        if checkpoint and checkpoint["phase"] != "complete":
            self.compose = ["docker", "compose", "-p", checkpoint["project"], "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
                            "--profile", "maintenance", "-f", "docker-compose.storage-production.yml"]
            self._resource_overlay()
            config = json.loads(self.dc("config", "--format", "json"))
            if str(config["services"]["worker"].get("environment", {}).get("MOBILE_PUSH_APNS_ENABLED", "false")).lower() in {"true", "1"}:
                self.compose.extend(["-f", "docker-compose.apns.yml"])
                config = json.loads(self.dc("config", "--format", "json"))
            self.resources.verify_binding(config)
            self.resource_config = config
            # Re-fence a partial activation before recovering any persistent
            # process. No previous application image is automatically restarted.
            self.resources.begin(config)
            from release_persistent_resources import recover_persistent_resources
            recover_persistent_resources(self, self.resources)
        recover_pending_storage_writers(self)
        super().activate()

    def complete_activation(self, config: dict[str, Any]) -> None:
        self.verify_resource_host()
        self.resources.verify_actual_limits(config, exact=self.env.get("RELEASE_RESOURCE_PROFILE") == "kvm4")
        self.resources.complete()

    def verify_resource_host(self) -> None:
        if self.env.get("RELEASE_RESOURCE_PROFILE") == "kvm4":
            endpoint = self.env.get("DOCKER_HOST") if not self.env.get("DOCKER_CONTEXT") else None
            endpoint = endpoint or self.run("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
            try:
                validate_local_swap_free_host(endpoint)
            except (OSError, ValueError) as error:
                raise ReleaseError(f"KVM4 physical host verification failed: {error}") from error

    def artifact_manifest(self) -> dict[str, Any]:
        configured = self.env.get("RELEASE_ARTIFACT_MANIFEST")
        if not configured:
            raise ReleaseError("Production activation requires RELEASE_ARTIFACT_MANIFEST from a signed, qualified CI release")
        manifest = verify_manifest(Path(configured), self.revision, pull=True, enforce_current_policy=True)
        if manifest["schema"] != self.expected_schema:
            raise ReleaseError("Promoted artifact schema differs from this release contract")
        return manifest

    def prepare_images(self, config: dict[str, Any], refs: dict[str, str]) -> dict[str, str]:
        if self.env.get("RELEASE_RESOURCE_PROFILE") == "kvm4":
            for reference in sorted({config["services"][name]["image"] for name in
                                     ("db", "redis", "redis-broker", "redis-realtime", "redis-cache", "clamav")}):
                if "@sha256:" not in reference:
                    raise ReleaseError("Persistent resource transition requires immutable image references")
                self.run("docker", "pull", reference, timeout=600)
                self.inspect(reference, image=True)
        if not self.env.get("RELEASE_ARTIFACT_MANIFEST"):
            self.say("LOCAL QUALIFICATION BUILD ONLY: production activate requires signed promoted artifacts")
            return super().prepare_images(config, refs)
        manifest = self.artifact_manifest()
        for name in self.activated_services:
            refs[name] = manifest["images"]["frontend" if name == "frontend" else "backend"]["reference"]
        return {name: manifest["images"]["frontend" if name == "frontend" else "backend"]["local_image_id"]
                for name in self.activated_services}

    def verify_promoted_release(self) -> None:
        manifest = self.artifact_manifest()
        if not self.manifest_path.is_file():
            raise ReleaseError("Signed artifacts are verified but this release has not been prepared")
        prepared = json.loads(self.manifest_path.read_text())
        expected = {name: manifest["images"]["frontend" if name == "frontend" else "backend"]["local_image_id"]
                    for name in self.activated_services}
        if prepared.get("images") != expected:
            raise ReleaseError("Prepared images differ from the signed CI-qualified artifacts; prepare again")

    def config_fingerprint(self, config: dict[str, Any]) -> str:
        path = Path(config["services"]["database-admin"]["environment"]["OBJECT_STORAGE_IDENTITY_FILE"])
        identity_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        profile_digest = ""
        if self.env.get("RELEASE_RESOURCE_PROFILE") == "kvm4":
            profile_digest = hashlib.sha256((self.root / "tooling/deployment-profiles/kvm4.json").read_bytes()).hexdigest()
        normalized = copy.deepcopy(config)
        for name in ("database-admin", "database-migrate"):
            normalized["services"][name].setdefault("environment", {}).update(
                APP_REVISION=self.revision, EXPECTED_DATABASE_SCHEMA_REVISION=self.expected_schema,
            )
        return hashlib.sha256((super().config_fingerprint(normalized) + identity_digest + profile_digest).encode()).hexdigest()

    def pinned_services(self, images: dict[str, str]) -> dict[str, dict[str, str]]:
        services = super().pinned_services(images)
        for name in ("database-admin", "database-migrate", "storage-copy"):
            services[name] = {"image": images["worker"], "pull_policy": "never"}
        return services

    def before_migration(self, current_schema: str) -> None:
        super().before_migration(current_schema)  # Verified new archive first.
        self.configure_persistent_resources()
        self.say("Provisioning restricted runtime and migration identities without deleting data")
        self.dc(
            "run", "--rm", "--no-deps", "database-admin", "python",
            "scripts/provision_database_roles.py", pinned=True, timeout=180,
        )
        self.storage.activate(json.loads(self.dc("config", "--format", "json")))

    def configure_persistent_resources(self) -> None:
        from release_persistent_resources import apply_persistent_resources
        assert self.resource_config is not None
        apply_persistent_resources(self, self.resources, self.resource_config)

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
        try:
            validate_process_isolation(actual_config["services"])
        except (KeyError, ValueError) as error:
            raise ReleaseError(f"Production native-library isolation rejected: {error}") from error
        budget = calculate_database_budget(actual_config, json.loads(
            (self.root / "tooling/database-deployment-budget.json").read_text()
        ))
        if budget["errors"]:
            raise ReleaseError("Deployment PostgreSQL budget rejected: " + "; ".join(budget["errors"]))
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
        self.resources.verify_binding(config)
        self.resources.plan(actual_config)
        if self.env.get("RELEASE_RESOURCE_PROFILE") == "kvm4":
            live = dict(item.split("=", 1) for item in self.container("backend")["Config"].get("Env", []) if "=" in item)
            try:
                if self.activating_release:
                    self.verify_resource_host()
                validate_profile(actual_config, json.loads((self.root / "tooling/deployment-profiles/kvm4.json").read_text()),
                                 activation=self.activating_release,
                                 my_photos_jobs=int(self.resources.sql("SELECT count(*) FROM public.my_photo_jobs")),
                                 live_backend_environment=live)
                current_storage = self.container("minio")
                if self.storage.maintained(current_storage):
                    host = current_storage["HostConfig"]
                    expected = actual_config["services"]["minio"]
                    memory = _memory_bytes(expected["mem_limit"])
                    if (host.get("Memory") != memory or host.get("MemorySwap") != memory
                            or host.get("NanoCpus") != int(float(expected["cpus"]) * 1_000_000_000)):
                        raise ValueError("Already-maintained storage has different actual caps; a separately qualified in-place resource transition is required")
            except (TypeError, ValueError, KeyError) as error:
                raise ReleaseError(f"KVM4 resource profile rejected: {error}") from error
        self.resource_config = actual_config
        return config


if __name__ == "__main__":
    raise SystemExit(run_release(CurrentRelease, description=__doc__))
