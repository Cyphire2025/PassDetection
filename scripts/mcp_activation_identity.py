"""Direct release identity responsibilities."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from mcp_activation_contract import WRITERS
from mcp_direct_build import BuildError
from mcp_direct_containers import LocalDocker
from mcp_direct_memory import capture as capture_memory
from mcp_direct_memory import compare as compare_memory
from mcp_direct_release import bound_original
from mcp_direct_state import WORKERS, DirectState, private_json


class _ActivationIdentity:
    if TYPE_CHECKING:
        state: DirectState
        client: LocalDocker
        baseline: dict[str, Any]
        originals: dict[str, Any]
        images: dict[str, Any]
        candidate_receipt: str
        project: str

        def start(self, candidate: dict[str, Any], service: str) -> None: ...

    def aliases(self, service: str) -> dict[str, str]:
        return {
            name: f"{self.project}-{service}"
            for name in self.originals[service]["NetworkSettings"]["Networks"]
        }

    def memory_checkpoint(
        self, label: str, rows: dict[str, Any], *, first: bool = False
    ) -> dict[str, Any]:
        snapshot = capture_memory(rows, inspect=bound_original)
        name = "oom-stage.private.json" if first else f"oom-{label}-{uuid.uuid4().hex}.json"
        private_json(self.state.directory / name, snapshot)
        if first:
            prepared = json.loads((self.state.directory / "oom-prepare.private.json").read_text())
            continuous = set(rows) - set(WORKERS)
            compare_memory(
                {"containers": {key: prepared["containers"][key] for key in continuous}},
                {"containers": {key: snapshot["containers"][key] for key in continuous}},
            )
        else:
            baseline = json.loads((self.state.directory / "oom-stage.private.json").read_text())
            compare_memory(
                {"containers": {key: baseline["containers"][key] for key in rows}},
                snapshot,
            )
        return snapshot

    def candidates(self) -> dict[str, Any]:
        rows = json.loads((self.state.directory / self.candidate_receipt).read_text())
        if not isinstance(rows, dict) or set(rows) != WRITERS:
            raise BuildError("candidate_service_inventory_changed")
        for value in rows.values():
            bound_original(value)
        return rows


# Keep canonical public method and pickle aliases in the stable facade.
for _name in ("aliases", "memory_checkpoint", "candidates"):
    _function = vars(_ActivationIdentity)[_name]
    _function.__module__ = "mcp_direct_activate"
    _function.__qualname__ = "DirectActivation." + _name
del _name, _function
