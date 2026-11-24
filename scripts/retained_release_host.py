"""Inspected inventory, source compatibility and retained resource evidence."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import release_pdf_checking_profile as pdf_profile
from mcp_direct_build import GIB, command
from mcp_direct_containers import LocalDocker
from mcp_direct_release import bound_original, wait_for_idle
from mcp_direct_state import INFRASTRUCTURE, WORKERS, private_json
from release_assistant_proxy_contract import PROXY_PATH, validate_assistant_proxy
from release_code_update import COMPATIBILITY_PATHS, task_contract
from release_manifest import load_release_manifest
from retained_release_contract import (
    ADDITIONAL_CONTRACT_PATHS,
    ROOT,
    ROUTE_ALLOWLIST,
    forbidden_changes,
    require,
    validate_route_allowlist,
)


class _RetainedHost:
    if TYPE_CHECKING:
        source: Path
        revision: str
        mode: str
        artifact: Path | None
        directory: Path
        client: LocalDocker
        record: dict[str, Any]
        pause_email_and_photos: bool
        project: str
        candidate_schema: str

        def retention_schema(self) -> str: ...

    def event(self, phase: str, **values: Any) -> None:
        self.record.update(phase=phase, **values)
        private_json(self.directory / f"{time.time_ns()}-{phase}.private.json", self.record)
        print(
            json.dumps({"phase": phase, "mode": self.mode, "revision": self.revision}), flush=True
        )

    def rows(self, *, all: bool = False) -> list[dict[str, Any]]:
        ids = command("docker", "ps", "-aq" if all else "-q", "--no-trunc").split()
        if not ids:
            return []
        # Retained release history can exceed a single command's output cap.
        # Keep every container while bounding each capture and the total wait.
        deadline = time.monotonic() + 120
        rows: list[dict[str, Any]] = []
        for offset in range(0, len(ids), 16):
            remaining = math.ceil(deadline - time.monotonic())
            require(remaining > 0, "docker_inventory_deadline_exceeded")
            batch = json.loads(command("docker", "inspect", *ids[offset:offset + 16], timeout=remaining))
            if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
                raise ValueError("invalid_docker_inventory")
            rows.extend(batch)
        return rows

    def paused_services(self) -> frozenset[str]:
        return pdf_profile.PAUSED if getattr(self, "pause_email_and_photos", False) else frozenset()

    def idle_workers(self, live: dict[str, Any]) -> dict[str, Any]:
        paused = self.paused_services()
        if not paused:
            return wait_for_idle(live)
        selected = {
            name: prefix
            for name, prefix in WORKERS.items()
            if name not in paused or live[name]["State"]["Running"]
        }
        return wait_for_idle(live, workers=selected)

    def schema(self) -> str:
        row = bound_original(self.record["live"]["db"])
        return command(
            "docker",
            "exec",
            row["Id"],
            "sh",
            "-c",
            'PGPASSWORD="$POSTGRES_PASSWORD" PGOPTIONS="-c default_transaction_read_only=on" '
            'exec psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
            '-c "SELECT version_num FROM public.alembic_version"',
        )

    def current_main(self) -> None:
        command("git", "-C", str(ROOT), "fetch", "origin", "main", timeout=180)
        require(
            command("git", "-C", str(ROOT), "rev-parse", "origin/main") == self.revision,
            "candidate_superseded_on_main",
        )

    def compatibility(self, previous: str) -> None:
        def git(*args: str) -> str:
            return command("git", "-C", str(self.source), *args)

        require(git("rev-parse", "HEAD") == self.revision, "candidate_source_revision_changed")
        require(
            not git("status", "--porcelain", "--untracked-files=no"), "candidate_source_modified"
        )
        git("merge-base", "--is-ancestor", previous, self.revision)
        paths = git(
            "diff",
            "--name-only",
            previous,
            self.revision,
            "--",
            *COMPATIBILITY_PATHS,
            *ADDITIONAL_CONTRACT_PATHS,
        ).splitlines()
        allowlist_checked = ROUTE_ALLOWLIST in paths
        if allowlist_checked:
            validate_route_allowlist(self.source)
        proxy_checked = PROXY_PATH in paths
        if proxy_checked:
            validate_assistant_proxy(
                git("show", f"{previous}:{PROXY_PATH}"),
                git("show", f"{self.revision}:{PROXY_PATH}"),
            )
        require(
            not forbidden_changes(paths, self.mode, route_allowlist_validated=allowlist_checked,
                                  assistant_proxy_validated=proxy_checked),
            "persistent_config_or_build_contract_requires_separate_release",
        )
        contract = load_release_manifest(
            self.source / "backend/app/core/config/release_manifest.json"
        )
        require(
            contract["schema_revision"] == self.candidate_schema
            and contract["worker_nodes"] == WORKERS,
            "separate_schema_or_worker_release_required",
        )
        # Existing additive release metadata describes the already-installed schema.
        # It is not authorization to rerun a migration. Exact migration/model/config
        # source identity above and observed live head below are both mandatory.
        for path in git(
            "diff", "--name-only", previous, self.revision, "--", "backend/app"
        ).splitlines():
            if path.endswith(".py"):
                old = (
                    git("show", f"{previous}:{path}")
                    if git("ls-tree", "--name-only", previous, "--", path)
                    else ""
                )
                new = (
                    git("show", f"{self.revision}:{path}")
                    if git("ls-tree", "--name-only", self.revision, "--", path)
                    else ""
                )
                require(task_contract(old) == task_contract(new), "queued_task_contract_changed")

    def retention(self) -> None:
        current = {row["Id"]: row for row in self.rows(all=True)}
        for identifier, original in self.record["inventory"].items():
            require(identifier in current, "previous_container_missing")
            bound_original(original)
        require(
            set(self.record["images_before"])
            <= set(command("docker", "image", "ls", "-q", "--no-trunc").split()),
            "previous_image_missing",
        )
        require(
            set(self.record["volumes_before"])
            <= set(command("docker", "volume", "ls", "-q").split()),
            "previous_volume_missing",
        )
        for name in INFRASTRUCTURE:
            require(
                bound_original(self.record["live"][name])["State"]["Running"],
                "infrastructure_stopped",
            )
        require(self.schema() == self.retention_schema(), "database_schema_changed")

    def backup(self) -> None:
        db = self.record["live"]["db"]["Id"]
        size = int(
            command(
                "docker",
                "exec",
                db,
                "sh",
                "-c",
                'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -XAt -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                '-c "SELECT pg_database_size(current_database())"',
            )
        )
        require(
            shutil.disk_usage(self.directory).free > 2 * size + 2 * GIB,
            "insufficient_backup_headroom",
        )
        path = self.directory / "pre-release.dump"
        with path.open("xb") as output:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    db,
                    "sh",
                    "-c",
                    'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
                ],
                stdout=output,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=600,
            )
            output.flush()
            os.fsync(output.fileno())
        with path.open("rb") as source:
            subprocess.run(
                ["docker", "exec", "-i", db, "pg_restore", "--list"],
                stdin=source,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=120,
            )
        self.event("backup-archive-listed", backup=str(path))


# Preserve public method aliases and pickle identities through the compatibility facade.
for _name in (
    "event",
    "rows",
    "paused_services",
    "idle_workers",
    "schema",
    "current_main",
    "compatibility",
    "retention",
    "backup",
):
    _function = vars(_RetainedHost)[_name]
    _function.__module__ = "release_retained_update"
    _function.__qualname__ = "RetainedUpdate." + _name
del _name, _function
