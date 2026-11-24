"""Direct release readiness responsibilities."""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from typing import Any

from mcp_activation_contract import ORIGIN, TARGET, WRITERS, clean_stop
from mcp_activation_database import _ActivationDatabase
from mcp_direct_build import BuildError, admit_builder, command
from mcp_direct_memory import capture as capture_memory
from mcp_direct_memory import compare as compare_memory
from mcp_direct_memory import require_zero
from mcp_direct_release import bound_original
from mcp_direct_state import INFRASTRUCTURE, private_json


class _ActivationReadiness(_ActivationDatabase):
    def start(self, candidate: dict[str, Any], service: str) -> None:
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
            if original
            else f"oom-start-{candidate['Id']}.json"
        )
        private_json(self.state.directory / receipt, snapshot)
        require_zero(snapshot)
        self.state.event(
            "original-started" if original else "candidate-started",
            service=service,
            container_id=candidate["Id"],
            memory_receipt=receipt,
        )

    def await_health(self, candidates: dict[str, Any], timeout: int = 180) -> None:
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
                check = (current["Config"].get("Healthcheck") or {}).get("Test", [])
                if health == "starting" or (check and check != ["NONE"] and health != "healthy"):
                    ready = False
            if time.monotonic() >= deadline:
                raise BuildError("candidate_health_deadline")
            if ready:
                return
            time.sleep(3)
        raise BuildError("candidate_health_deadline")

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
                self.state.directory / f"oom-verified-{candidate['Id']}-{uuid.uuid4().hex}.json",
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
                headers={
                    "User-Agent": "Mozilla/5.0 GlobalConnectsRelease/1.0",
                    "Cache-Control": "no-cache",
                },
            )
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read(131072))
                if response.status != 200:
                    raise BuildError("public_readiness_failed")
                if path.endswith("/health/live") and payload.get("revision") != self.state.revision:
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


# Keep canonical public method and pickle aliases in the stable facade.
for _name in ("start", "await_health", "verify"):
    _function = vars(_ActivationReadiness)[_name]
    _function.__module__ = "mcp_direct_activate"
    _function.__qualname__ = "DirectActivation." + _name
del _name, _function
