"""Explicit retained retry baseline after a fully recovered source-schema attempt.

This operator overlay never starts/stops a container, modifies staged source, or
replaces an earlier receipt. Bind it to one existing DirectActivation instance.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from types import MethodType

from mcp_direct_build import BuildError, command
from mcp_direct_memory import capture, compare, require_zero
from mcp_direct_release import bound_original
from mcp_direct_state import INFRASTRUCTURE, SERVICES, private_json

SOURCE_SCHEMA = "0113_document_follow_up"
OVERLAY_MODULES = (
    "mcp_direct_activate",
    "mcp_direct_retry",
    "mcp_direct_release",
    "mcp_direct_state",
    "mcp_direct_memory",
    "mcp_direct_containers",
    "mcp_direct_build",
    "release_mcp_database",
)


def _read(path: Path) -> tuple[dict, str]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
            raise ValueError("receipt")
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TypeError("receipt")
        return value, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError):
        raise BuildError("retry_receipt_unavailable") from None


def _originals_ready(activation) -> None:
    if set(activation.originals) != SERVICES:
        raise BuildError("retry_original_inventory_changed")
    for original in activation.originals.values():
        current = bound_original(original)
        state = current["State"]
        health = state.get("Health", {}).get("Status")
        healthcheck = current["Config"].get("Healthcheck", {}).get("Test", [])
        if (
            current["Id"] != original["Id"]
            or state.get("Running") is not True
            or state.get("Paused")
            or state.get("Restarting")
            or (health is not None and health != "healthy")
            or (healthcheck and healthcheck != ["NONE"] and health != "healthy")
        ):
            raise BuildError("retry_original_not_healthy")
    running = set(command("docker", "ps", "-q", "--no-trunc").split())
    if running != {value["Id"] for value in activation.originals.values()}:
        raise BuildError("retry_helper_candidate_or_original_inventory_changed")
    for candidate in activation.candidates().values():
        if bound_original(candidate)["State"].get("Running"):
            raise BuildError("retry_candidate_running")
    if activation.schema() != SOURCE_SCHEMA:
        raise BuildError("retry_requires_original_schema")


def _compare_recovery(before: dict, after: dict) -> list[str]:
    """Only explicitly recovered app cgroups may reset; infrastructure never may."""
    try:
        if (
            set(before["containers"]) != SERVICES
            or set(after["containers"]) != SERVICES
        ):
            raise ValueError("inventory")
        restarted = []
        for service in SERVICES:
            first, last = before["containers"][service], after["containers"][service]
            if first["id"] != last["id"]:
                raise ValueError("identity")
            previous = {"containers": {service: first}}
            current = {"containers": {service: last}}
            if (
                service in INFRASTRUCTURE
                or first["started_at"] == last["started_at"]
            ):
                compare(previous, current)
            else:
                if not {"oom", "oom_kill"} <= last["events"].keys():
                    raise ValueError("counters")
                require_zero(current)
                restarted.append(service)
        return sorted(restarted)
    except (ValueError, KeyError, TypeError):
        raise BuildError("retry_recovery_memory_binding_changed") from None


def _overlay_sources() -> dict:
    result = {}
    for name in OVERLAY_MODULES:
        module = sys.modules.get(name)
        filename = getattr(module, "__file__", None)
        if filename is None:
            raise BuildError("retry_overlay_module_unavailable")
        path = Path(filename).resolve()
        result[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return result


def bind_retry_baseline(activation, snapshot_path: Path) -> dict:
    """Validate recovery, retain a new named baseline, then bind this instance only.

    The caller invokes activation.activate() separately. The original stage,
    recovery start receipts, and source manifest are never rewritten.
    """
    directory = activation.state.directory.resolve()
    if (
        snapshot_path.parent.resolve() != directory
        or not re.fullmatch(
            r"oom-retry-[a-z0-9-]{1,64}\.private\.json", snapshot_path.name
        )
        or snapshot_path.exists()
        or snapshot_path.is_symlink()
        or hasattr(activation, "_retry_baseline_path")
    ):
        raise BuildError("retry_requires_new_explicit_snapshot")
    activation.state.verify_source()
    activation.state.verify_retention(activation.baseline)
    _originals_ready(activation)
    previous, previous_hash = _read(directory / "oom-stage.private.json")
    current = capture(activation.originals, inspect=bound_original)
    restarted = _compare_recovery(previous, current)
    recovery_receipts = {}
    for service in restarted:
        row = current["containers"][service]
        paths = list(directory.glob(f"oom-original-start-{row['id']}-*.json"))
        legacy = directory / f"oom-start-{row['id']}.json"
        if legacy.exists():
            paths.append(legacy)
        for path in paths:
            evidence, digest = _read(path)
            saved = evidence.get("containers", {}).get(service, {})
            if saved.get("id") == row["id"] and saved.get("started_at") == row["started_at"]:
                compare(evidence, {"containers": {service: row}})
                recovery_receipts[service] = {"filename": path.name, "sha256": digest}
                break
        else:
            raise BuildError("retry_recovered_start_receipt_unavailable")
    _originals_ready(activation)
    overlay = _overlay_sources()
    current["retry"] = {
        "revision": activation.state.revision,
        "schema": SOURCE_SCHEMA,
        "previous_stage_sha256": previous_hash,
        "recovered_services": restarted,
        "recovery_receipts": recovery_receipts,
        "operator_modules": overlay,
    }
    private_json(snapshot_path, current)
    _, expected_hash = _read(snapshot_path)
    activation.state.event(
        "retry-memory-baseline-bound",
        filename=snapshot_path.name,
        sha256=expected_hash,
        original_stage_sha256=previous_hash,
        recovered_services=restarted,
        operator_modules=overlay,
    )

    def checkpoint(self, label: str, rows: dict, *, first: bool = False) -> dict:
        if first or not re.fullmatch(r"[a-z][a-z0-9-]{0,80}", label):
            raise BuildError("retry_cannot_restage_or_use_invalid_checkpoint")
        retained, actual_hash = _read(snapshot_path)
        if actual_hash != expected_hash or not set(rows) <= set(self.originals):
            raise BuildError("retry_baseline_or_inventory_changed")
        observed = capture(rows, inspect=bound_original)
        private_json(directory / f"oom-retry-{label}-{uuid.uuid4().hex}.json", observed)
        compare(
            {"containers": {key: retained["containers"][key] for key in rows}},
            observed,
        )
        return observed

    activation._retry_baseline_path = snapshot_path
    activation.memory_checkpoint = MethodType(checkpoint, activation)
    return current
