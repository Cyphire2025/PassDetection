"""Validate a rendered production Compose memory budget without starting it.

Example: docker compose ... config --format json --no-env-resolution > compose.json
python scripts/verify_deployment_resource_budget.py compose.json --host-memory-gib 24
The input may contain credentials; keep it outside source control and never print it.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shlex
from decimal import Decimal
from pathlib import Path


_BYTE_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
}


def _memory_bytes(value: object) -> int:
    # Rendered Compose normally emits integer bytes; byte strings are also legal.
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("mem_limit must be a positive byte value")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmgt]?b?)", str(value).strip().lower())
    if not match:
        raise ValueError("mem_limit must be a positive byte value")
    result = Decimal(match[1]) * _BYTE_UNITS[match[2]]
    if result <= 0 or result != result.to_integral_value():
        raise ValueError("mem_limit must be a positive whole number of bytes")
    return int(result)


def _nonnegative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("requires a nonnegative integer")
    if not re.fullmatch(r"\d+", str(value)):
        raise ValueError("requires a nonnegative integer")
    return int(value)


def _replicas(service: dict) -> int:
    deploy = service.get("deploy", {})
    if not isinstance(deploy, dict) or deploy.get("mode", "replicated") != "replicated":
        raise ValueError("requires a finite replicated service count")
    replicas = _nonnegative_integer(deploy.get("replicas", service.get("scale", 1)))
    if "scale" in service and _nonnegative_integer(service["scale"]) != replicas:
        raise ValueError("scale and deploy.replicas must agree")
    return replicas


def _worker_children(command: object) -> int | None:
    if command is None:
        return None  # Image CMD is outside the rendered Compose command.
    if isinstance(command, str):
        tokens = shlex.split(command)
    elif isinstance(command, list) and all(isinstance(value, str) for value in command):
        tokens = command
    else:
        raise ValueError("command must be a string or an array of strings")
    if "worker" not in tokens or not any(
        token.rsplit("/", 1)[-1] == "celery" for token in tokens
    ):
        return None
    limits = []
    for index, token in enumerate(tokens):
        option, separator, value = token.partition("=")
        if option in {"--concurrency", "-c", "--autoscale"}:
            if not separator:
                value = tokens[index + 1] if index + 1 < len(tokens) else ""
            if option == "--autoscale":
                parts = value.split(",")
                if len(parts) != 2:
                    raise ValueError(
                        "Celery autoscale must declare maximum and minimum children"
                    )
                maximum, minimum = map(_nonnegative_integer, parts)
                if minimum > maximum:
                    raise ValueError("Celery autoscale minimum exceeds its maximum")
                limits.append(maximum)
            else:
                limits.append(_nonnegative_integer(value))
        elif token.startswith("-c") and token[2:].isdigit():
            limits.append(int(token[2:]))
    if not limits or min(limits) <= 0:
        raise ValueError(
            "Celery worker requires explicit positive concurrency or autoscale maximum"
        )
    return max(limits)


def validate_budget(
    config: object, host_gib: float, reserve_gib: float
) -> tuple[list[str], float]:
    failures: list[str] = []
    if (
        not math.isfinite(host_gib)
        or not math.isfinite(reserve_gib)
        or host_gib <= 0
        or reserve_gib < 0
    ):
        return [
            "Host memory must be finite and positive; reserve must be finite and nonnegative"
        ], 0.0
    if (
        not isinstance(config, dict)
        or not isinstance(config.get("services"), dict)
        or not config["services"]
    ):
        return ["Rendered Compose must contain a nonempty services mapping"], 0.0
    total = 0
    for name, service in config["services"].items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
            failures.append("Compose contains an invalid service name")
            continue
        if not isinstance(service, dict):
            failures.append(f"{name}: service definition must be a mapping")
            continue
        try:
            memory = _memory_bytes(service.get("mem_limit"))
            replicas = _replicas(service)
            total += memory * replicas
        except ValueError as error:
            failures.append(f"{name}: {error}")
            continue
        try:
            cpu = service.get("cpus")
            if (
                isinstance(cpu, bool)
                or not isinstance(cpu, (int, float, str))
                or not math.isfinite(float(cpu))
                or float(cpu) <= 0
            ):
                raise ValueError
        except (ValueError, OverflowError):
            failures.append(f"{name}: requires an explicit finite positive CPU ceiling")
        try:
            children = _worker_children(service.get("command"))
        except ValueError:
            # Do not echo parser errors: a command can contain credentials.
            failures.append(
                f"{name}: command must declare valid positive Celery concurrency or autoscale limits"
            )
            continue
        if children and (256 + children * 128) * 1024**2 > memory:
            failures.append(
                f"{name}: worker count exceeds the conservative 128 MiB/child plus 256 MiB parent allowance; measure before increasing it"
            )
    total_gib = total / 1024**3
    if total_gib + reserve_gib > host_gib:
        failures.append(
            f"Container ceilings {total_gib:.2f} GiB + host reserve {reserve_gib:.2f} GiB exceed {host_gib:.2f} GiB"
        )
    return failures, total_gib


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rendered_compose", type=Path)
    parser.add_argument("--host-memory-gib", type=float, required=True)
    parser.add_argument("--reserve-gib", type=float, default=2)
    args = parser.parse_args()
    if (
        not math.isfinite(args.host_memory_gib)
        or not math.isfinite(args.reserve_gib)
        or args.host_memory_gib <= 0
        or args.reserve_gib < 0
    ):
        parser.error(
            "Host memory must be finite and positive; reserve finite and nonnegative"
        )
    try:
        config = json.loads(args.rendered_compose.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        # JSON and file errors may include private input. Fail without dumping it.
        parser.error(
            "Cannot read rendered Compose JSON; check the local file and encoding"
        )
    failures, total = validate_budget(config, args.host_memory_gib, args.reserve_gib)
    for failure in failures:
        print(failure)
    if not failures:
        print(
            f"Memory envelope verified: {total:.2f} GiB of containers + {args.reserve_gib:.2f} GiB host reserve"
        )
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
