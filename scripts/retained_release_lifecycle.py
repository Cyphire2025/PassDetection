"""Retained release lifecycle and generation-exclusive transition/recovery."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

import release_pdf_checking_profile as pdf_profile
from mcp_direct_build import GIB, command
from mcp_direct_containers import LocalDocker
from mcp_direct_release import bound_original
from mcp_direct_state import APPLICATION, INFRASTRUCTURE, WORKERS
from release_artifacts import verify_manifest
from release_code_update import environment
from retained_release_build import _RetainedBuild
from retained_release_contract import REVISION, ROOT, SCHEMA, require, select_live


class RetainedUpdate(_RetainedBuild):
    candidate_schema = SCHEMA

    def initial_schema(self) -> str:
        return self.candidate_schema

    def prepare_images(self) -> None:
        """Same-schema updates need no migration identity."""

    def before_candidate_start(self) -> None:
        require(self.schema() == self.candidate_schema, "same_schema_required_before_start")

    def retention_schema(self) -> str:
        return self.candidate_schema

    def __init__(
        self, source: Path, revision: str, mode: str, artifact: Path | None = None
    ) -> None:
        require(
            REVISION.fullmatch(revision) is not None and mode in {"full", "fast"},
            "invalid_release_selection",
        )
        require(
            source.resolve() == source
            and source.is_relative_to(ROOT / "tmp")
            and source.parent.name.startswith("mcp-direct-")
            and source.name == "source",
            "invalid_release_source",
        )
        require(
            (mode == "full") == (artifact is not None),
            "full_requires_manifest_fast_forbids_manifest",
        )
        self.source, self.revision, self.mode, self.artifact = source, revision, mode, artifact
        self.directory = source.parent
        self.client = LocalDocker()
        self.record = {}
        self.pause_email_and_photos = False
        self.project = "retained-" + revision[:12] + "-" + uuid.uuid4().hex[:8]

    def recover(self) -> None:
        self.event("recovering")
        self.retention()
        candidates = self.record.get("candidates", {})
        for name in ("nginx", "email-beat", "backend", "frontend", *WORKERS):
            if name in candidates:
                self.fence_candidate(candidates[name])
        require(
            {row["Id"] for row in self.rows()}
            <= {row["Id"] for row in self.record["live"].values()},
            "unexpected_running_container_blocks_recovery",
        )
        for name in ("backend", "frontend", *WORKERS, "email-beat"):
            if self.record["live"][name]["State"]["Running"]:
                self.start(self.record["live"][name])
        self.proof(
            {name: self.record["live"][name] for name in APPLICATION},
            self.record["previous_revision"],
            public=False,
        )
        self.start(self.record["live"]["nginx"])
        self.proof(self.record["live"], self.record["previous_revision"], public=True)
        self.event("recovered-originals")

    def run(self) -> None:
        require(
            not list(self.directory.glob("*-prepared.private.json")),
            "existing_attempt_requires_receipt_review",
        )
        running = self.rows()
        inventory = (
            pdf_profile.live_inventory(running, self.rows(all=True))
            if self.paused_services()
            else running
        )
        live = select_live(
            inventory, schema=self.initial_schema(), paused_services=self.paused_services()
        )
        previous = environment(live["backend"])["APP_REVISION"]
        self.compatibility(previous)
        self.current_main()
        total = sum(row["HostConfig"]["Memory"] for row in running)
        require(
            all(
                type(row["HostConfig"]["Memory"]) is int and row["HostConfig"]["Memory"] > 0
                for row in live.values()
            )
            and total + 2 * GIB <= int(command("docker", "info", "--format", "{{.MemTotal}}")),
            "steady_capacity_exceeds_host_reserve",
        )
        require(not Path("/proc/swaps").read_text().splitlines()[1:], "swap_must_remain_disabled")
        profile_budget = (
            pdf_profile.planned_budget(
                live, int(command("docker", "info", "--format", "{{.MemTotal}}"))
            )
            if self.paused_services()
            else None
        )
        self.record = {
            "revision": self.revision,
            "mode": self.mode,
            "schema": self.initial_schema(),
            "project": self.project,
            "source": str(self.source),
            "previous_revision": previous,
            "live": live,
            "inventory": {row["Id"]: row for row in self.rows(all=True)},
            "images_before": command("docker", "image", "ls", "-q", "--no-trunc").split(),
            "volumes_before": command("docker", "volume", "ls", "-q").split(),
            "pause_email_and_photos": bool(self.paused_services()),
            "runtime_profile_budget": profile_budget,
        }
        self.event("prepared")
        require(
            self.schema() == self.initial_schema(), "same_schema_required_no_migration_permitted"
        )
        self.proof(live, previous, public=True)
        require(
            shutil.disk_usage(self.directory).free >= 12 * GIB,
            "insufficient_retained_image_headroom",
        )
        self.prepare_images()
        if self.mode == "full":
            if self.artifact is None:
                raise ValueError("full_requires_manifest_fast_forbids_manifest")
            manifest = verify_manifest(
                self.artifact, self.revision, pull=True, enforce_current_policy=True
            )
            require(manifest["schema"] == self.candidate_schema, "signed_image_schema_mismatch")
            images = {name: entry["local_image_id"] for name, entry in manifest["images"].items()}
            self.event("signed-images-verified", image_ids=images)
        else:
            images = self.fast_images()
        self.backup()
        candidates = self.stage(images)
        self.transition(candidates)

    def transition(self, candidates: dict[str, Any]) -> None:
        live = self.record["live"]
        self.current_main()
        try:
            # Builds resume the original scheduler/workers. Drain them again
            # while ingress remains available: a stuck warm shutdown must not
            # take down the website before a replacement can safely start.
            self.event("precutover-draining")
            self.stop(bound_original(live["email-beat"]))
            self.event("precutover-workers-idle", worker_idle=self.idle_workers(live))
            for name in WORKERS:
                self.stop(bound_original(live[name]))
            self.event("cutover-starting")
            for name in ("nginx", "backend", "frontend"):
                self.stop(bound_original(live[name]))
            require(
                {row["Id"] for row in self.rows()} == {live[name]["Id"] for name in INFRASTRUCTURE},
                "writers_not_fenced",
            )
            self.before_candidate_start()
            for name in ("backend", "frontend", *WORKERS, "email-beat"):
                if name not in self.paused_services():
                    self.start(candidates[name])
            self.proof(
                {name: candidates[name] for name in APPLICATION}, self.revision, public=False
            )
            self.start(candidates["nginx"])
            self.proof(candidates, self.revision, public=True)
            require(
                {row["Id"] for row in self.rows()}
                == {
                    row["Id"]
                    for name, row in candidates.items()
                    if name not in self.paused_services()
                }
                | {live[name]["Id"] for name in INFRASTRUCTURE},
                "unexpected_running_container",
            )
            if self.paused_services():
                for name in self.paused_services():
                    require(
                        not bound_original(candidates[name])["State"]["Running"],
                        "paused_worker_started",
                    )
                pdf_profile.planned_budget(
                    {**live, **candidates},
                    int(command("docker", "info", "--format", "{{.MemTotal}}")),
                )
            self.retention()
            self.event("complete", all_prior_resources_retained=True, automatic_downgrade=False)
        except BaseException:
            try:
                self.recover()
            except BaseException:
                self.event("recovery-required")
                raise ValueError("recovery_required_inspect_retained_receipts") from None
            raise


# Preserve public method aliases and pickle identities through the compatibility facade.
for _name in (
    "initial_schema",
    "prepare_images",
    "before_candidate_start",
    "retention_schema",
    "__init__",
    "recover",
    "run",
    "transition",
):
    _function = vars(RetainedUpdate)[_name]
    _function.__module__ = "release_retained_update"
    _function.__qualname__ = "RetainedUpdate." + _name
del _name, _function

RetainedUpdate.__module__ = "release_retained_update"
