"""Finish only an owned synthetic QA container and retain all its artifacts."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

OWNER_LABEL = "globalconnects.qa-probe-owner"


class ProbeCommand(Protocol):
    def __call__(self, *arguments: str, timeout: int = 120) -> str: ...


@dataclass
class ProbeCleanup:
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    errors: list[BaseException] = field(default_factory=list)


@dataclass
class OwnedProbeContainer:
    name: str
    image_id: str
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    identifier: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", self.image_id):
            raise ValueError("An exact local QA image ID is required")

    def options(self) -> list[str]:
        return ["--name", self.name, "--label", f"{OWNER_LABEL}={self.token}"]

    def bind_returned_id(self, identifier: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise ValueError("Docker did not return a complete owned container ID")
        self.identifier = identifier

    def inspect_owned(self, command: ProbeCommand) -> dict[str, Any]:
        rows = json.loads(
            command("docker", "inspect", self.identifier or self.name, timeout=10)
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("Owned QA container inspection is ambiguous")
        row = rows[0]
        if not isinstance(row, dict):
            raise TypeError("Owned QA container inspection is not an object")
        identifier = row.get("Id", "")
        if (
            not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or row.get("Image") != self.image_id
            or row.get("Name") != "/" + self.name
            or row.get("Config", {}).get("Labels", {}).get(OWNER_LABEL) != self.token
            or (self.identifier is not None and identifier != self.identifier)
        ):
            raise ValueError("QA container ownership differs from this invocation")
        self.identifier = identifier
        if not isinstance(row.get("State"), dict) or not isinstance(
            row["State"].get("Running"), bool
        ):
            raise TypeError("Owned QA container state cannot be verified")
        return row

    def finish(self, command: ProbeCommand, *, stop_seconds: int = 30) -> ProbeCleanup:
        """A returned immutable ID remains authority when diagnostics fail.

        Without that ID, only exact name, image and unpredictable owner-label
        agreement permits adoption. No removal or broad name cleanup occurs.
        """
        result = ProbeCleanup()
        try:
            result.before = self.inspect_owned(command)["State"]
        except BaseException as error:  # noqa: BLE001 - defer errors until owned cleanup finishes.
            result.errors.append(error)
        if self.identifier is None:
            return result
        if result.before is not None and result.before.get("Running") is False:
            result.after = result.before
            return result

        for _ in range(2):
            try:
                command(
                    "docker",
                    "stop",
                    "--time",
                    str(stop_seconds),
                    self.identifier,
                    timeout=stop_seconds + 10,
                )
            except BaseException as error:  # noqa: BLE001 - defer errors until owned cleanup finishes.
                result.errors.append(error)
            try:
                result.after = self.inspect_owned(command)["State"]
            except BaseException as error:  # noqa: BLE001 - defer errors until owned cleanup finishes.
                result.errors.append(error)
            if result.after is not None and result.after.get("Running") is False:
                return result
        result.errors.append(
            RuntimeError("Owned QA container stop could not be verified")
        )
        return result


def error_types(errors: list[BaseException]) -> list[str]:
    """Keep diagnostics useful without copying driver or command payloads."""
    return [type(error).__name__ for error in errors]
