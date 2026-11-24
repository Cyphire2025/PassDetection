"""Pure projections used by the rendered Compose policy checks."""

from __future__ import annotations

from typing import Any


def _command_text(service: dict[str, Any]) -> str:
    command = service.get("command")
    if command is None:
        return ""
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command)


def _volume_targets(service: dict[str, Any]) -> set[str]:
    return {
        str(volume.get("target"))
        for volume in service.get("volumes", [])
        if isinstance(volume, dict) and volume.get("target")
    }


def _healthcheck_text(service: dict[str, Any]) -> str:
    test = service.get("healthcheck", {}).get("test", [])
    if isinstance(test, list):
        return " ".join(str(part) for part in test)
    return str(test)


def _published_port_targets(service: dict[str, Any]) -> set[int]:
    targets: set[int] = set()
    for port in service.get("ports", []):
        if not isinstance(port, dict) or port.get("published") is None:
            continue
        target = port.get("target")
        if isinstance(target, int):
            targets.add(target)
        elif isinstance(target, str) and target.isdigit():
            targets.add(int(target))
    return targets


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


for _export in (
    _command_text,
    _volume_targets,
    _healthcheck_text,
    _published_port_targets,
    _require,
):
    _export.__module__ = "verify_compose_runtime"
del _export
