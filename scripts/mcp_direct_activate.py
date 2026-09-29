"""Retained direct cutover: fence writers, validate backup, migrate, start clones."""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from mcp_direct_build import GIB, BuildError, admit_builder, command
from mcp_direct_containers import LocalDocker, clone_payload
from mcp_direct_memory import capture as capture_memory
from mcp_direct_memory import compare as compare_memory
from mcp_direct_memory import require_zero
from mcp_direct_release import bound_original, inspect, require_idle
from mcp_direct_state import (
    APPLICATION,
    INFRASTRUCTURE,
    ROOT,
    WORKERS,
    DirectState,
    fingerprint,
    private_json,
)
from release_mcp_database import MCPDatabaseRelease, ReleaseBindings

TARGET = "0122_mcp_gc_push"
ORIGIN = "https://tech.gctravels.com"
WRITERS = APPLICATION | {"nginx"}


def environment(container: dict) -> dict[str, str]:
    return dict(
        value.split("=", 1) for value in container["Config"]["Env"] if "=" in value
    )


def runtime_environment(original: dict, revision: str) -> dict[str, str]:
    result = environment(original)
    if original["Config"]["Labels"]["com.docker.compose.service"] == "frontend":
        result["NEXT_PUBLIC_APP_REVISION"] = revision
    else:
        result.update(
            APP_REVISION=revision,
            EXPECTED_DATABASE_SCHEMA_REVISION=TARGET,
            PYTHONPATH="/opt/mcp-deps:/app",
            MCP_ENABLED="true",
            MCP_ENABLED_CAPABILITIES='["mcp:read","mcp:export"]',
            MCP_EXPORT_FAMILIES='["passport_excel"]',
            MCP_EXPORT_SOURCE_ROW_LIMIT="100",
            MCP_EXPORT_SOURCE_BYTE_LIMIT="1048576",
            MCP_PUBLIC_ORIGIN=ORIGIN,
            MCP_FRONTEND_ORIGIN=ORIGIN,
            MCP_APPROVED_CLIENTS='{"global-connects-desktop":["http://127.0.0.1:8765/callback"]}',
        )
    return result


def render_proxy(config: str, backend_alias: str, frontend_alias: str) -> str:
    for source, target in (
        ("server backend:8000;", f"server {backend_alias}:8000;"),
        ("server frontend:3000;", f"server {frontend_alias}:3000;"),
    ):
        if config.count(source) != 1:
            raise BuildError("proxy_upstream_binding_changed")
        config = config.replace(source, target)
    return config


def clean_stop(container: dict, original: dict | None = None) -> None:
    state = container["State"]
    # The observed original proxy retains an old OOMKilled flag. Preserve that
    # evidence; only a newly set flag is a stop failure. New clones stay strict.
    prior_oom = original is not None and original["State"].get("OOMKilled") is True
    # The retained Node standalone server exits with 128 + SIGTERM after the
    # proxy has drained. This is expected for that stateless frontend only.
    frontend_term = (
        container.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "frontend"
        and container["Config"].get("Cmd") == ["node", "server.js"]
        and state.get("ExitCode") == 143
    )
    if (
        state["Running"]
        or (state.get("ExitCode") != 0 and not frontend_term)
        or (state.get("OOMKilled") and not prior_oom)
        or (
            original is not None
            and container.get("RestartCount", 0) != original.get("RestartCount", 0)
        )
    ):
        raise BuildError("application_not_cleanly_drained")


class DirectActivation:
    def __init__(self, state: DirectState, *, image_receipt: str = "images.json", project_suffix: str = ""):
        if not re.fullmatch(r"images(?:-[a-z0-9-]{1,40})?\.json", image_receipt) or not re.fullmatch(r"(?:-[a-z0-9]{1,16})?", project_suffix):
            raise BuildError("invalid_retained_attempt_binding")
        self.state, self.client = state, LocalDocker()
        self.baseline = state.load_baseline()
        self.originals = self.baseline["containers"]
        self.images = json.loads((state.directory / image_receipt).read_text())
        self.candidate_receipt = "candidates.private.json"
        if self.images.get("revision") != state.revision:
            raise BuildError("image_receipt_revision_changed")
        for service in ("backend", "frontend"):
            record = self.images[service]
            if record["base_image_id"] != self.originals[service]["Image"]:
                raise BuildError("built_image_base_changed")
            image = json.loads(
                command("docker", "image", "inspect", record["image_id"])
            )[0]
            if (
                image["Id"] != record["image_id"]
                or image["Config"]["Labels"].get("org.opencontainers.image.revision")
                != state.revision
            ):
                raise BuildError("candidate_image_identity_changed")
        self.project = f"mcp-direct-{state.revision[:12]}{project_suffix}"

    def aliases(self, service: str) -> dict[str, str]:
        return {
            name: f"{self.project}-{service}"
            for name in self.originals[service]["NetworkSettings"]["Networks"]
        }

    def memory_checkpoint(self, label: str, rows: dict, *, first: bool = False) -> dict:
        snapshot = capture_memory(rows, inspect=bound_original)
        name = (
            "oom-stage.private.json"
            if first
            else f"oom-{label}-{uuid.uuid4().hex}.json"
        )
        private_json(self.state.directory / name, snapshot)
        if first:
            prepared = json.loads(
                (self.state.directory / "oom-prepare.private.json").read_text()
            )
            continuous = set(rows) - set(WORKERS)
            compare_memory(
                {
                    "containers": {
                        key: prepared["containers"][key] for key in continuous
                    }
                },
                {
                    "containers": {
                        key: snapshot["containers"][key] for key in continuous
                    }
                },
            )
        else:
            baseline = json.loads(
                (self.state.directory / "oom-stage.private.json").read_text()
            )
            compare_memory(
                {"containers": {key: baseline["containers"][key] for key in rows}},
                snapshot,
            )
        return snapshot

    def stage(self, *, candidate_receipt: str = "candidates.private.json") -> None:
        if not re.fullmatch(r"candidates(?:-[a-z0-9-]{1,40})?\.private\.json", candidate_receipt):
            raise BuildError("invalid_retained_candidate_receipt")
        if (self.state.directory / candidate_receipt).exists():
            raise BuildError("candidate_stage_already_retained")
        for original in self.originals.values():
            if not bound_original(original)["State"]["Running"]:
                raise BuildError("stage_requires_original_services_running")
        self.memory_checkpoint("stage", self.originals, first=not hasattr(self, "_retry_baseline_path"))
        # Resolve existing maintenance credentials without changing roles or .env.
        resolved = json.loads(
            command(
                "docker",
                "compose",
                "--project-directory",
                str(ROOT),
                "--env-file",
                str(ROOT / ".env"),
                "-f",
                str(ROOT / "docker-compose.yml"),
                "-f",
                str(ROOT / "docker-compose.prod.yml"),
                "--profile",
                "maintenance",
                "config",
                "--format",
                "json",
            )
        )
        maintenance = resolved["services"]["database-migrate"]["environment"]
        credentials = {
            key: maintenance[key] for key in ("POSTGRES_USER", "POSTGRES_PASSWORD")
        }
        if any(
            not isinstance(value, str) or not value for value in credentials.values()
        ):
            raise BuildError("existing_migration_credentials_unavailable")
        credential_path = self.state.directory / "migration-credentials.private.json"
        if credential_path.exists():
            if credential_path.is_symlink() or json.loads(credential_path.read_text()) != credentials:
                raise BuildError("retained_migration_credentials_changed")
        else:
            private_json(credential_path, credentials)
        proxy = self.state.directory / "runtime-nginx" / self.project
        proxy.mkdir(mode=0o700, parents=True)
        for relative in ("nginx.conf", "conf.d"):
            source = self.state.source / "nginx" / relative
            paths = [source] if source.is_file() else sorted(source.rglob("*"))
            for path in paths:
                if not path.is_file():
                    continue
                target = proxy / path.relative_to(self.state.source / "nginx")
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = path.read_bytes()
                if relative == "nginx.conf":
                    raw = render_proxy(
                        raw.decode(),
                        next(iter(self.aliases("backend").values())),
                        next(iter(self.aliases("frontend").values())),
                    ).encode()
                with target.open("xb") as stream:
                    stream.write(raw)
        candidates = {}
        for service in sorted(WRITERS):
            original = self.originals[service]
            image_id = (
                original["Image"]
                if service == "nginx"
                else self.images["frontend" if service == "frontend" else "backend"][
                    "image_id"
                ]
            )
            overrides = (
                {
                    "/etc/nginx/nginx.conf": str(proxy / "nginx.conf"),
                    "/etc/nginx/conf.d": str(proxy / "conf.d"),
                }
                if service == "nginx"
                else None
            )
            identifier = self.client.create_clone(
                original,
                name=f"{self.project}-{service}",
                image_id=image_id,
                environment=environment(original)
                if service == "nginx"
                else runtime_environment(original, self.state.revision),
                new_project=self.project,
                source_root=str(self.state.source),
                aliases=self.aliases(service),
                nginx_mount_overrides=overrides,
            )
            candidates[service] = inspect(identifier)
            self.state.event(
                "candidate-container-retained", service=service, container_id=identifier
            )
        private_json(self.state.directory / candidate_receipt, candidates)
        self.candidate_receipt = candidate_receipt
        self.state.verify_retention(self.baseline)
        self.state.event("candidate-stage-complete")

    def candidates(self) -> dict:
        rows = json.loads(
            (self.state.directory / self.candidate_receipt).read_text()
        )
        if set(rows) != WRITERS:
            raise BuildError("candidate_service_inventory_changed")
        for value in rows.values():
            bound_original(value)
        return rows

    def fence(self) -> None:
        self.state.verify_source()
        for service in WRITERS:
            clean_stop(bound_original(self.originals[service]), self.originals[service])
        for value in self.candidates().values():
            if bound_original(value)["State"]["Running"]:
                raise BuildError("candidate_writer_running_before_migration")
        running = set(command("docker", "ps", "-q", "--no-trunc").split())
        if running != {self.originals[name]["Id"] for name in INFRASTRUCTURE}:
            raise BuildError("unexpected_running_container_during_writer_fence")
        for service in INFRASTRUCTURE:
            current = bound_original(self.originals[service])
            previous_networks = self.originals[service]["NetworkSettings"]["Networks"]
            if current["NetworkSettings"]["Networks"] != previous_networks:
                raise BuildError("infrastructure_network_binding_changed")
        self.memory_checkpoint(
            "fenced-infrastructure",
            {key: self.originals[key] for key in INFRASTRUCTURE},
        )
        self.state.verify_retention(self.baseline)

    def database_command(
        self,
        arguments: tuple[str, ...],
        *,
        timeout: int,
        stdin_file=None,
        stdout_file=None,
    ) -> str:
        db = bound_original(self.originals["db"])
        result = subprocess.run(
            ["docker", "exec", "-i", db["Id"], *arguments],
            stdin=stdin_file if stdin_file is not None else subprocess.DEVNULL,
            stdout=stdout_file if stdout_file is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        if result.returncode or (result.stdout and len(result.stdout) > 1024 * 1024):
            raise BuildError("database_command_failed")
        return result.stdout.decode().strip() if result.stdout else ""

    def schema(self) -> str:
        return self.database_command(
            (
                "sh",
                "-c",
                (
                    'export PGPASSWORD="$POSTGRES_PASSWORD"; '
                    'exec psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                    '-c "SELECT version_num FROM public.alembic_version"'
                ),
            ),
            timeout=30,
        )

    def start(self, candidate: dict, service: str) -> None:
        rows = command("docker", "ps", "-q", "--no-trunc").split()
        running = json.loads(command("docker", "inspect", *rows)) if rows else []
        admit_builder(
            running,
            int(command("docker", "info", "--format", "{{.MemTotal}}")),
            candidate["HostConfig"]["Memory"],
        )
        self.client.start(candidate["Id"])
        snapshot = capture_memory({service: candidate}, inspect=bound_original)
        # Recovery may start the same retained original more than once. Keep
        # every start receipt; candidate verification still binds its first run.
        original = any(row["Id"] == candidate["Id"] for row in self.originals.values())
        receipt = (
            f"oom-original-start-{candidate['Id']}-{uuid.uuid4().hex}.json"
            if original else f"oom-start-{candidate['Id']}.json"
        )
        private_json(
            self.state.directory / receipt, snapshot
        )
        require_zero(snapshot)
        self.state.event(
            "original-started" if original else "candidate-started",
            service=service, container_id=candidate["Id"], memory_receipt=receipt,
        )

    def migrate(self) -> None:
        self.fence()
        bindings = ReleaseBindings(
            self.state.revision,
            self.images["backend"]["image_id"],
            fingerprint(self.originals["db"]),
            fingerprint({name: self.originals[name]["Id"] for name in sorted(WRITERS)}),
        )
        database = MCPDatabaseRelease(
            self.state.source,
            self.state.directory,
            bindings,
            database_command=self.database_command,
            verify_fence=self.fence,
            read_schema=self.schema,
        )
        backup = database.backup()
        self.state.event(
            "database-backup-validated",
            filename=backup["filename"],
            bytes=backup["bytes"],
            sha256=backup["sha256"],
        )
        request = database.migration_request(backup)
        env = runtime_environment(self.originals["backend"], self.state.revision)
        env.update(
            json.loads(
                (
                    self.state.directory / "migration-credentials.private.json"
                ).read_text()
            )
        )
        env.update(request["environment"], APP_ENV="development", MCP_ENABLED="false")
        payload = clone_payload(
            self.originals["backend"],
            name=self.project + "-migration",
            image_id=request["image_id"],
            environment=env,
            new_project=self.project,
            source_root=str(self.state.source),
            aliases={
                key: self.project + "-migration" for key in self.aliases("backend")
            },
        )
        # Keep a short-lived helper alive until its exact cgroup is admitted.
        # The upgrade cannot begin before the operator creates this unique gate.
        gate = "/tmp/mcp-migration-" + uuid.uuid4().hex
        barrier = (
            "import os,signal,sys,time; "
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); "
            "deadline=time.monotonic()+120\n"
            "while not os.path.exists(sys.argv[1]):\n"
            " if time.monotonic()>deadline:sys.exit(3)\n"
            " time.sleep(0.1)\n"
            "os.execvp(sys.argv[2],sys.argv[2:])"
        )
        payload.update(
            Cmd=["python", "-B", "-c", barrier, gate, *request["arguments"]],
            Entrypoint=[],
            Healthcheck={"Test": ["NONE"]},
        )
        payload["HostConfig"].update(
            Memory=GIB,
            MemorySwap=GIB,
            NanoCpus=1_000_000_000,
            RestartPolicy={"Name": "no", "MaximumRetryCount": 0},
        )
        helper = self.client.request(
            "POST", "/containers/create?name=" + self.project + "-migration", payload
        )["Id"]
        self.state.event(
            "migration-helper-retained", container_id=helper, proof=request["proof"]
        )
        self.fence()
        try:
            self.start(inspect(helper), "database-migration")
        except Exception:
            # No gate exists yet, so this helper cannot have run database work.
            stopped = self.client.graceful_stop(helper, timeout=30)
            if stopped["State"]["Running"]:
                raise BuildError("migration_admission_helper_still_running")
            raise
        command("docker", "exec", helper, "python", "-B", "-c", "import sys;open(sys.argv[1],'x').close()", gate)
        code = command("docker", "wait", helper, timeout=request["timeout"])
        current = inspect(helper)
        if code != "0":
            raise BuildError("migration_failed_forward_repair_required")
        clean_stop(current)
        database.verify_target(backup)
        self.state.event(
            "database-migration-verified", schema=TARGET, backup_sha256=backup["sha256"]
        )

    def await_health(self, candidates: dict, timeout: int = 180) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready = True
            for expected in candidates.values():
                current = bound_original(expected)
                status = current["State"]
                if (
                    not status["Running"]
                    or status.get("OOMKilled")
                    or current.get("RestartCount", 0)
                ):
                    raise BuildError("candidate_exit_oom_or_restart")
                health = status.get("Health", {}).get("Status")
                if health == "unhealthy":
                    raise BuildError("candidate_health_failed")
                if health == "starting":
                    ready = False
            if ready:
                return
            time.sleep(3)
        raise BuildError("candidate_health_deadline")

    def activate(self) -> None:
        candidates = self.candidates()
        if self.schema() != "0113_document_follow_up":
            raise BuildError(
                "activation_requires_original_schema_forward_repair_otherwise"
            )
        for value in self.originals.values():
            if not bound_original(value)["State"]["Running"]:
                raise BuildError("activation_requires_original_services_running")
        for value in candidates.values():
            if bound_original(value)["State"]["Running"]:
                raise BuildError("candidate_already_running")
        self.memory_checkpoint("before-drain", self.originals)
        self.state.event("application-drain-started")
        for service in ("email-beat", "nginx"):
            self.memory_checkpoint(
                "before-stop-" + service, {service: self.originals[service]}
            )
            clean_stop(
                self.client.graceful_stop(self.originals[service]["Id"], timeout=120),
                self.originals[service],
            )
            self.state.event("original-service-drained", service=service)
        require_idle(self.originals)
        for service in (*WORKERS, "frontend", "backend"):
            self.memory_checkpoint(
                "before-stop-" + service, {service: self.originals[service]}
            )
            clean_stop(
                self.client.graceful_stop(self.originals[service]["Id"], timeout=120),
                self.originals[service],
            )
            self.state.event("original-service-drained", service=service)
        # Every failure leaves exact identities and artifacts retained. After the
        # upgrade, only forward repair is allowed; never restart the old schema client.
        self.migrate()
        for service in (*WORKERS, "email-beat", "backend", "frontend"):
            self.start(candidates[service], service)
        self.await_health(
            {key: value for key, value in candidates.items() if key != "nginx"}
        )
        self.start(candidates["nginx"], "nginx")
        self.verify()

    def recover_original(self) -> None:
        """Explicit pre-upgrade recovery only; target schema always fails closed."""
        self.state.verify_source()
        if self.schema() != "0113_document_follow_up":
            raise BuildError("original_recovery_requires_source_schema")
        for candidate in self.candidates().values():
            if bound_original(candidate)["State"]["Running"]:
                raise BuildError("original_recovery_candidate_running")
        running = set(command("docker", "ps", "-q", "--no-trunc").split())
        if not running <= {item["Id"] for item in self.originals.values()}:
            raise BuildError("original_recovery_unexpected_running_container")
        for service in INFRASTRUCTURE:
            current = bound_original(self.originals[service])
            if (
                not current["State"]["Running"]
                or current["NetworkSettings"]["Networks"]
                != self.originals[service]["NetworkSettings"]["Networks"]
            ):
                raise BuildError("original_recovery_infrastructure_changed")
        stopped = {}
        for service in WRITERS:
            current = bound_original(self.originals[service])
            if not current["State"]["Running"]:
                clean_stop(current, self.originals[service])
                stopped[service] = current
        # Validate every stopped process before restarting any process. In
        # particular a still-running migration helper must never race recovery.
        self.state.event(
            "original-recovery-validated", schema="0113_document_follow_up"
        )
        for service in (*WORKERS, "backend", "frontend", "email-beat", "nginx"):
            if service in stopped:
                if self.schema() != "0113_document_follow_up":
                    raise BuildError("original_recovery_schema_changed")
                self.start(stopped[service], service)
        self.state.verify_retention(self.baseline)
        self.state.event(
            "original-services-recovered", schema="0113_document_follow_up"
        )

    def verify(self) -> None:
        candidates = self.candidates()
        self.await_health(candidates)
        if self.schema() != TARGET:
            raise BuildError("live_schema_mismatch")
        self.memory_checkpoint(
            "verified-infrastructure",
            {key: self.originals[key] for key in INFRASTRUCTURE},
        )
        for service, candidate in candidates.items():
            before = json.loads(
                (self.state.directory / f"oom-start-{candidate['Id']}.json").read_text()
            )
            after = capture_memory({service: candidate}, inspect=bound_original)
            private_json(
                self.state.directory
                / f"oom-verified-{candidate['Id']}-{uuid.uuid4().hex}.json",
                after,
            )
            compare_memory(before, after)
        for service in WRITERS:
            clean_stop(bound_original(self.originals[service]), self.originals[service])
        enabled = self.database_command(
            (
                "sh",
                "-c",
                (
                    'export PGPASSWORD="$POSTGRES_PASSWORD"; '
                    'exec psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                    '-c "SELECT enabled FROM public.mcp_control WHERE id=1"'
                ),
            ),
            timeout=30,
        )
        if enabled != "f":
            raise BuildError("initial_mcp_control_not_disabled")
        for path in (
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/.well-known/oauth-protected-resource/mcp",
        ):
            request = urllib.request.Request(
                ORIGIN + path,
                headers={"User-Agent": "Mozilla/5.0 GlobalConnectsRelease/1.0", "Cache-Control": "no-cache"},
            )
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read(131072))
                if response.status != 200:
                    raise BuildError("public_readiness_failed")
                if (
                    path.endswith("/health/live")
                    and payload.get("revision") != self.state.revision
                ):
                    raise BuildError("public_application_revision_mismatch")
                if path.endswith("/health/ready") and payload.get("status") != "ready":
                    raise BuildError("public_readiness_failed")
                if (
                    path.endswith("oauth-protected-resource/mcp")
                    and payload.get("resource") != ORIGIN + "/mcp"
                ):
                    raise BuildError("public_mcp_metadata_mismatch")
        self.state.verify_retention(self.baseline)
        self.state.event(
            "direct-release-live-verified",
            schema=TARGET,
            original_containers_retained=True,
            mcp_database_control_enabled=False,
            mcp_capabilities=["mcp:read", "mcp:export"],
        )
