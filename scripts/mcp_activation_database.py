"""Direct release database responsibilities."""

from __future__ import annotations

import json
import subprocess
import uuid
from typing import BinaryIO

from mcp_activation_contract import TARGET, WRITERS, clean_stop, runtime_environment
from mcp_activation_staging import _ActivationStaging
from mcp_direct_build import GIB, BuildError, command
from mcp_direct_containers import clone_payload
from mcp_direct_release import bound_original, inspect
from mcp_direct_state import INFRASTRUCTURE, fingerprint
from release_mcp_database import MCPDatabaseRelease, ReleaseBindings


class _ActivationDatabase(_ActivationStaging):
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
        stdin_file: BinaryIO | None = None,
        stdout_file: BinaryIO | None = None,
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
            json.loads((self.state.directory / "migration-credentials.private.json").read_text())
        )
        env.update(request["environment"], APP_ENV="development", MCP_ENABLED="false")
        payload = clone_payload(
            self.originals["backend"],
            name=self.project + "-migration",
            image_id=request["image_id"],
            environment=env,
            new_project=self.project,
            source_root=str(self.state.source),
            aliases={key: self.project + "-migration" for key in self.aliases("backend")},
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
            "POST",
            "/containers/create?name=" + self.project + "-migration-" + uuid.uuid4().hex[:12],
            payload,
        )["Id"]
        self.state.event("migration-helper-retained", container_id=helper, proof=request["proof"])
        self.fence()
        try:
            self.start(inspect(helper), "database-migration")
        except Exception:
            # No gate exists yet, so this helper cannot have run database work.
            stopped = self.client.graceful_stop(helper, timeout=30)
            if stopped["State"]["Running"]:
                raise BuildError("migration_admission_helper_still_running")
            raise
        command(
            "docker",
            "exec",
            helper,
            "python",
            "-B",
            "-c",
            "import sys;open(sys.argv[1],'x').close()",
            gate,
        )
        code = command("docker", "wait", helper, timeout=request["timeout"])
        current = inspect(helper)
        if code != "0":
            raise BuildError("migration_failed_forward_repair_required")
        clean_stop(current)
        database.verify_target(backup)
        self.state.event(
            "database-migration-verified", schema=TARGET, backup_sha256=backup["sha256"]
        )


# Keep canonical public method and pickle aliases in the stable facade.
for _name in ("fence", "database_command", "schema", "migrate"):
    _function = vars(_ActivationDatabase)[_name]
    _function.__module__ = "mcp_direct_activate"
    _function.__qualname__ = "DirectActivation." + _name
del _name, _function
