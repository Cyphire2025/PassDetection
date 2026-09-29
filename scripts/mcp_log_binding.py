"""Read-only Docker commands bound to an explicit local Compose deployment."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.logging.mcp_log_normalization import COLLECTED_SERVICES
from app.core.logging.mcp_log_projection import diagnostic_timestamp
from mcp_log_stream import bounded_metadata

MAX_CONTAINERS = 32
PROJECT = "com.docker.compose.project"
DIRECTORY = "com.docker.compose.project.working_dir"
SERVICE = "com.docker.compose.service"
ONEOFF = "com.docker.compose.oneoff"
INSPECT_FORMAT = (
    '{"id":{{json .Id}},"running":{{json .State.Running}},'
    '"started":{{json .State.StartedAt}},"image":{{json .Image}},'
    + ",".join(
        f'"{key}":{{{{json (index .Config.Labels "{label}")}}}}'
        for key, label in (
            ("project", PROJECT),
            ("root", DIRECTORY),
            ("service", SERVICE),
            ("oneoff", ONEOFF),
        )
    )
    + "}"
)


class BindingError(ValueError):
    """Only static failure codes may be raised at this boundary."""


@dataclass(frozen=True)
class Binding:
    identifier: str
    service: str
    started: str
    image: str


class DockerBinding:
    def __init__(
        self,
        root: Path,
        project: str,
        deadline: float,
        *,
        metadata: Callable[..., bytes] = bounded_metadata,
    ):
        if (
            not root.is_absolute()
            or root.is_symlink()
            or not root.is_dir()
            or root.resolve() != root
        ):
            raise BindingError("invalid_deployment_root")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
            raise BindingError("invalid_compose_project")
        self.root, self.project, self.deadline, self.metadata = (
            root,
            project,
            deadline,
            metadata,
        )

    def probe(self, *arguments: str) -> bytes:
        if time.monotonic() >= self.deadline:
            raise BindingError("collection_deadline")
        try:
            return self.metadata(
                ("docker", *arguments),
                deadline=min(self.deadline, time.monotonic() + 5),
            )
        except (OSError, ValueError, TimeoutError):
            raise BindingError("binding_probe_failed") from None

    def require_local(self) -> None:
        if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
            raise BindingError("remote_docker_forbidden")
        try:
            endpoint = json.loads(
                self.probe(
                    "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"
                )
            )
        except (ValueError, TypeError):
            raise BindingError("binding_probe_failed") from None
        if endpoint != "unix:///var/run/docker.sock":
            raise BindingError("remote_docker_forbidden")

    def inspect(self, identifiers: list[str]) -> list[dict[str, Any]]:
        if (
            not identifiers
            or len(identifiers) > MAX_CONTAINERS
            or any(not re.fullmatch("[a-f0-9]{64}", item) for item in identifiers)
        ):
            raise BindingError("invalid_container_inventory")
        try:
            rows = [
                json.loads(line)
                for line in self.probe(
                    "inspect", "--format", INSPECT_FORMAT, *identifiers
                ).splitlines()
            ]
            if len(rows) != len(identifiers) or any(
                not isinstance(row, dict) for row in rows
            ):
                raise ValueError()
            if {row.get("id") for row in rows} != set(identifiers):
                raise ValueError()
            return rows
        except (ValueError, TypeError):
            raise BindingError("binding_probe_failed") from None

    def parse(self, row: dict[str, Any]) -> Binding | None:
        if (
            row.get("project") != self.project
            or row.get("root") != str(self.root)
            or row.get("running") is not True
        ):
            raise BindingError("binding_changed")
        if row.get("oneoff") != "False" or row.get("service") not in COLLECTED_SERVICES:
            return None
        if (
            diagnostic_timestamp(row.get("started")) is None
            or not isinstance(row.get("image"), str)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", row["image"])
        ):
            raise BindingError("binding_changed")
        return Binding(row["id"], row["service"], row["started"], row["image"])

    def discover(self) -> dict[str, list[Binding]]:
        self.require_local()
        raw = self.probe(
            "ps",
            "--no-trunc",
            "--filter",
            f"label={PROJECT}={self.project}",
            "--filter",
            f"label={DIRECTORY}={self.root}",
            "--filter",
            "status=running",
            "--format",
            "{{.ID}}",
        )
        identifiers = raw.decode("ascii").splitlines()
        if not identifiers:
            raise BindingError("source_unavailable")
        if len(set(identifiers)) != len(identifiers):
            raise BindingError("invalid_container_inventory")
        result: dict[str, list[Binding]] = {}
        for row in self.inspect(identifiers):
            binding = self.parse(row)
            if binding is not None:
                result.setdefault(binding.service, []).append(binding)
        return result

    def unchanged(self, binding: Binding) -> None:
        current = (
            self.probe(
                "ps",
                "--no-trunc",
                "--filter",
                f"label={PROJECT}={self.project}",
                "--filter",
                f"label={DIRECTORY}={self.root}",
                "--filter",
                f"label={SERVICE}={binding.service}",
                "--filter",
                f"label={ONEOFF}=False",
                "--filter",
                "status=running",
                "--format",
                "{{.ID}}",
            )
            .decode("ascii")
            .splitlines()
        )
        if current != [binding.identifier]:
            raise BindingError("binding_changed")
        if self.parse(self.inspect([binding.identifier])[0]) != binding:
            raise BindingError("binding_changed")

    @staticmethod
    def logs(binding: Binding, since: str, until: str) -> tuple[str, ...]:
        return (
            "docker",
            "logs",
            "--timestamps",
            "--since",
            since,
            "--until",
            until,
            "--tail",
            "2000",
            binding.identifier,
        )
