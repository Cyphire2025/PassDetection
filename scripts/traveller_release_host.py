"""Host commands, checkout binding and durable private release files."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from traveller_release_contract import (
    PROJECT_LABEL,
    SERVICE_LABEL,
    ReleaseError,
    updated_environment,
)


class _ReleaseHost:
    if TYPE_CHECKING:
        root: Path
        revision: str
        expected_schema: str
        phase: str
        env: dict[str, str]
        compose: list[str]
        pin_path: Path
        directory: Path
        preserve_release_artifacts: bool
        workers: tuple[str, ...]
        activated_services: tuple[str, ...]

    def run(self, *args: str, timeout: int = 90, stream: bool = False) -> str:
        try:
            result = subprocess.run(
                args,
                cwd=self.root,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=None if stream else subprocess.PIPE,
                stderr=None if stream else subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ReleaseError(
                f"{self.phase}: command could not finish ({type(error).__name__})"
            ) from error
        if result.returncode:
            # Inspection/configuration output can contain credentials. Never echo it.
            raise ReleaseError(f"{self.phase}: {' '.join(args[:3])} exited {result.returncode}")
        return (result.stdout or "").strip()

    def dc(self, *args: str, pinned: bool = False, **kwargs: Any) -> str:
        override = ["-f", str(self.pin_path)] if pinned else []
        return self.run(*self.compose, *override, *args, **kwargs)

    def inspect(self, identifier: str, *, image: bool = False) -> dict[str, Any]:
        args = ("docker", "image", "inspect") if image else ("docker", "inspect")
        data = json.loads(self.run(*args, identifier))
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise ReleaseError("Docker did not return one inspectable object")
        return data[0]

    def say(self, phase: str) -> None:
        self.phase = phase
        print(phase, flush=True)

    def verify_checkout(self) -> None:
        if self.run("git", "rev-parse", "HEAD") != self.revision:
            raise ReleaseError("Checkout does not match --revision; pull the intended commit first")
        self.run("git", "merge-base", "--is-ancestor", self.revision, "origin/main")
        self.run("git", "diff", "--quiet", "HEAD", "--")
        untracked = self.run(
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "backend",
            "frontend",
        )
        if untracked:
            raise ReleaseError(
                "Untracked application files can affect the build; preserve/review them before release"
            )

    def verify_running_project(self) -> dict[str, Any]:
        """Identify the existing project without rendering or changing .env."""
        current = self.inspect("passdetection-backend")
        labels = current.get("Config", {}).get("Labels") or {}
        project = labels.get(PROJECT_LABEL)
        if (
            not project
            or labels.get(SERVICE_LABEL) != "backend"
            or not current.get("State", {}).get("Running")
        ):
            raise ReleaseError(
                "The existing production backend must be running with Compose labels"
            )
        working_dir = labels.get("com.docker.compose.project.working_dir")
        if working_dir and Path(working_dir).resolve() != self.root:
            raise ReleaseError(
                "This checkout is not the existing backend's Compose working directory"
            )
        self.compose = [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.prod.yml",
        ]
        return current

    def preflight(self) -> dict[str, Any]:
        self.verify_checkout()
        if not (self.root / ".env").is_file():
            raise ReleaseError("The existing production .env is missing")
        self.verify_running_project()
        config = json.loads(self.dc("config", "--format", "json"))
        if (
            not isinstance(config, dict)
            or config.get("name") != self.compose[3]
            or not {*self.activated_services, "nginx"} <= set(config.get("services", {}))
        ):
            raise ReleaseError("The resolved Compose project is missing required release services")
        return config

    def config_fingerprint(self, config: dict[str, Any]) -> str:
        # The two intentional release variables are normalized before hashing .env.
        env_text = updated_environment(
            (self.root / ".env").read_text(), self.revision, self.expected_schema
        )
        resolved = copy.deepcopy(config)
        for service, definition in resolved["services"].items():
            environment = definition.setdefault("environment", {})
            for key, value in {
                "APP_REVISION": self.revision,
                "EXPECTED_DATABASE_SCHEMA_REVISION": self.expected_schema,
            }.items():
                if key in environment or service in (*self.workers, "backend"):
                    environment[key] = value
        value = json.dumps(resolved, sort_keys=True, separators=(",", ":")) + "\n" + env_text
        return hashlib.sha256(value.encode()).hexdigest()

    def write_private(self, path: Path, data: str, *, exclusive: bool = False) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.directory.chmod(0o700)
        if exclusive:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            self.sync_directory(path.parent)
            return
        descriptor, filename = tempfile.mkstemp(prefix=".traveller-release-", dir=path.parent)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, "w") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            self.sync_directory(path.parent)
        finally:
            if not self.preserve_release_artifacts:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def sync_directory(path: Path) -> None:
        if os.name == "posix":
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def verify_image(self, identifier: str, *, backend: bool) -> str:
        image = self.inspect(identifier, image=True)
        image_id = image.get("Id", "")
        if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ReleaseError("Docker returned an invalid image ID")
        if backend:
            env = dict(
                value.split("=", 1) for value in image["Config"].get("Env", []) if "=" in value
            )
            revision = (image["Config"].get("Labels") or {}).get(
                "org.opencontainers.image.revision"
            )
            if env.get("APP_REVISION") != self.revision or revision != self.revision:
                raise ReleaseError(
                    "Built backend/worker image does not contain the intended revision"
                )
        return image_id


# Keep original public method/pickle names through the stable facade.
for _name in (
    "run",
    "dc",
    "inspect",
    "say",
    "verify_checkout",
    "verify_running_project",
    "preflight",
    "config_fingerprint",
    "write_private",
    "sync_directory",
    "verify_image",
):
    _member = vars(_ReleaseHost)[_name]
    _function = _member.__func__ if isinstance(_member, staticmethod) else _member
    _function.__module__ = "release_traveller_whatsapp"
    _function.__qualname__ = "Release." + _name
del _name, _member, _function
