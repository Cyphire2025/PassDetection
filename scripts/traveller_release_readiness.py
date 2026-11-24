"""Current container, worker and schema identity probes."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from traveller_release_contract import (
    CONTROL_PROBE,
    PROBE_MARKER,
    PROJECT_LABEL,
    SERVICE_LABEL,
    ReleaseError,
    validate_worker_probe,
)
from traveller_release_host import _ReleaseHost


class _ReleaseReadiness(_ReleaseHost):
    if TYPE_CHECKING:
        node_prefixes: dict[str, str]
        schema_service: str

    def container(self, service: str) -> dict[str, Any]:
        # Inspect the existing deployment without rendering candidate Compose:
        # its required cutover credentials may not exist in the old .env yet.
        ids = self.run(
            "docker",
            "ps",
            "--quiet",
            "--filter",
            f"label={PROJECT_LABEL}={self.compose[3]}",
            "--filter",
            f"label={SERVICE_LABEL}={service}",
        ).split()
        if len(ids) != 1:
            raise ReleaseError(f"{service}: expected exactly one running container")
        container = self.inspect(ids[0])
        labels = container.get("Config", {}).get("Labels") or {}
        if (
            not container.get("State", {}).get("Running")
            or labels.get(SERVICE_LABEL) != service
            or labels.get(PROJECT_LABEL) != self.compose[3]
        ):
            raise ReleaseError(f"{service}: running container identity does not match this project")
        return container

    def worker_probe(self, *, idle: bool) -> None:
        nodes = set()
        for service, prefix in self.node_prefixes.items():
            hostname = self.container(service).get("Config", {}).get("Hostname")
            if not isinstance(hostname, str) or not hostname:
                raise ReleaseError(f"{service}: worker hostname is missing")
            nodes.add(f"{prefix}@{hostname}")
        output = self.dc(
            "exec",
            "-T",
            "worker",
            "python",
            "-c",
            CONTROL_PROBE,
            json.dumps(sorted(nodes)),
            "idle" if idle else "ping",
            timeout=55,
        )
        payloads = [
            line[len(PROBE_MARKER) :]
            for line in output.splitlines()
            if line.startswith(PROBE_MARKER)
        ]
        if len(payloads) != 1:
            raise ReleaseError("Worker probe did not return one complete result")
        validate_worker_probe(
            json.loads(payloads[0]), nodes, idle=idle, expected_count=len(self.node_prefixes)
        )

    def verify_containers(self, services: tuple[str, ...], images: dict[str, str]) -> None:
        for service in services:
            container = self.container(service)
            if container.get("Image") != images[service]:
                raise ReleaseError(f"{service}: running image is not the prepared image ID")
            if service != "frontend":
                env = dict(
                    item.split("=", 1) for item in container["Config"].get("Env", []) if "=" in item
                )
                if (
                    env.get("APP_REVISION") != self.revision
                    or env.get("EXPECTED_DATABASE_SCHEMA_REVISION") != self.expected_schema
                ):
                    raise ReleaseError(f"{service}: running revision/schema setting is incorrect")

    def schema(self) -> str:
        output = self.dc(
            "run",
            *(() if self.preserve_release_artifacts else ("--rm",)),
            "--no-deps",
            self.schema_service,
            "alembic",
            "current",
            pinned=True,
            timeout=180,
        )
        matches: list[str] = re.findall(
            r"^([0-9]{4}_[A-Za-z0-9_]+)(?:\s|$)", output, flags=re.MULTILINE
        )
        if len(matches) != 1:
            raise ReleaseError("Could not verify the database's single Alembic revision")
        return matches[0]


# Keep original public method/pickle names through the stable facade.
for _name in ("container", "worker_probe", "verify_containers", "schema"):
    _member = vars(_ReleaseReadiness)[_name]
    _function = _member.__func__ if isinstance(_member, staticmethod) else _member
    _function.__module__ = "release_traveller_whatsapp"
    _function.__qualname__ = "Release." + _name
del _name, _member, _function
