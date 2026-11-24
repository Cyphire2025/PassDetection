"""Direct release lifecycle responsibilities."""

from __future__ import annotations

import json
import re

from mcp_activation_contract import WRITERS, clean_stop
from mcp_activation_readiness import _ActivationReadiness
from mcp_direct_build import BuildError, command
from mcp_direct_containers import LocalDocker
from mcp_direct_release import bound_original, require_idle
from mcp_direct_state import INFRASTRUCTURE, WORKERS, DirectState


class DirectActivation(_ActivationReadiness):
    def __init__(
        self, state: DirectState, *, image_receipt: str = "images.json", project_suffix: str = ""
    ) -> None:
        if not re.fullmatch(
            r"images(?:-[a-z0-9-]{1,40})?\.json", image_receipt
        ) or not re.fullmatch(r"(?:-[a-z0-9]{1,16})?", project_suffix):
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
            image = json.loads(command("docker", "image", "inspect", record["image_id"]))[0]
            if (
                image["Id"] != record["image_id"]
                or image["Config"]["Labels"].get("org.opencontainers.image.revision")
                != state.revision
            ):
                raise BuildError("candidate_image_identity_changed")
        self.project = f"mcp-direct-{state.revision[:12]}{project_suffix}"

    def activate(self) -> None:
        candidates = self.candidates()
        if self.schema() != "0113_document_follow_up":
            raise BuildError("activation_requires_original_schema_forward_repair_otherwise")
        for value in self.originals.values():
            if not bound_original(value)["State"]["Running"]:
                raise BuildError("activation_requires_original_services_running")
        for value in candidates.values():
            if bound_original(value)["State"]["Running"]:
                raise BuildError("candidate_already_running")
        self.memory_checkpoint("before-drain", self.originals)
        self.state.event("application-drain-started")
        for service in ("email-beat", "nginx"):
            self.memory_checkpoint("before-stop-" + service, {service: self.originals[service]})
            clean_stop(
                self.client.graceful_stop(self.originals[service]["Id"], timeout=120),
                self.originals[service],
            )
            self.state.event("original-service-drained", service=service)
        require_idle(self.originals)
        for service in (*WORKERS, "frontend", "backend"):
            self.memory_checkpoint("before-stop-" + service, {service: self.originals[service]})
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
        self.await_health({key: value for key, value in candidates.items() if key != "nginx"})
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
        self.state.event("original-recovery-validated", schema="0113_document_follow_up")
        for service in (*WORKERS, "backend", "frontend", "email-beat", "nginx"):
            if service in stopped:
                if self.schema() != "0113_document_follow_up":
                    raise BuildError("original_recovery_schema_changed")
                self.start(stopped[service], service)
        self.state.verify_retention(self.baseline)
        self.state.event("original-services-recovered", schema="0113_document_follow_up")


# Keep canonical public method and pickle aliases in the stable facade.
for _name in ("__init__", "activate", "recover_original"):
    _function = vars(DirectActivation)[_name]
    _function.__module__ = "mcp_direct_activate"
    _function.__qualname__ = "DirectActivation." + _name
del _name, _function

DirectActivation.__module__ = "mcp_direct_activate"
