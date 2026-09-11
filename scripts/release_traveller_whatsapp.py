"""Two-stage VPS release for the traveller WhatsApp feature (migration 0093).

Run prepare while the current site is available. Pause new uploads and message
sends before activate; its worker snapshots are a gate, not a traffic barrier.
This helper never pulls/reset/stashes Git, purges queues, or restarts infrastructure.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "0093_phone_welcome"
PREVIOUS_SCHEMA = "0092_whatsapp_matching_fields"
NODE_PREFIXES = {
    "worker": "general",
    "email-worker": "email",
    "email-ai-worker": "email-ai",
    "extraction-worker": "extraction",
    "verification-worker": "verification",
    "visa-ai-worker": "visa-ai",
    "my-photos-worker": "my-photos",
}
WORKERS = (*NODE_PREFIXES, "email-beat")
ACTIVATED = (*WORKERS, "backend", "frontend")
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
PUBLIC_URL = "https://tech.gctravels.com"
PROBE_MARKER = "TRAVELLER_RELEASE_PROBE="
CONTROL_PROBE = """
import json, sys
from app.infrastructure.processing.celery_app import celery_app
nodes = json.loads(sys.argv[1])
inspector = celery_app.control.inspect(destination=nodes, timeout=10)
methods = ('ping',) if sys.argv[2] == 'ping' else ('active', 'reserved', 'scheduled')
print('TRAVELLER_RELEASE_PROBE=' + json.dumps({key: getattr(inspector, key)() for key in methods}))
"""
READY_PROBE = """
import urllib.request
with urllib.request.urlopen('http://localhost:8000/api/v1/health/ready', timeout=10) as r:
    assert r.status == 200, r.status
print('Backend readiness: 200')
"""


class ReleaseError(RuntimeError):
    pass


def updated_environment(text: str, revision: str) -> str:
    values = {"APP_REVISION": revision, "EXPECTED_DATABASE_SCHEMA_REVISION": SCHEMA}
    seen: set[str] = set()
    lines = []
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Z_]+)\s*=", line)
        key = match.group(1) if match else None
        if key in values:
            if key not in seen:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in values.items() if key not in seen)
    return "\n".join(lines) + "\n"


def validate_worker_probe(payload: Any, nodes: set[str], *, idle: bool) -> None:
    methods = ("active", "reserved", "scheduled") if idle else ("ping",)
    if not isinstance(payload, dict) or set(payload) != set(methods):
        raise ReleaseError("Worker inspection is incomplete; no activation is allowed")
    for method in methods:
        replies = payload[method]
        if not isinstance(replies, dict) or set(replies) != nodes or len(nodes) != 7:
            raise ReleaseError(f"{method}: all seven exact worker nodes must reply")
        for node, tasks in replies.items():
            if idle and (not isinstance(tasks, list) or tasks):
                raise ReleaseError(
                    f"{method}: {node} is busy or returned invalid task data; wait and retry"
                )
            if not idle and (not isinstance(tasks, dict) or tasks.get("ok") != "pong"):
                raise ReleaseError(f"{node} has not become ready")


def image_reference(config: dict[str, Any], images: set[str], service: str) -> str:
    explicit = config["services"][service].get("image")
    if explicit:
        if explicit not in images:
            raise ReleaseError(
                f"{service}: configured image was not resolved by Compose"
            )
        return str(explicit)
    # Ask Compose which spelling it actually generated (compatibility mode uses '_').
    candidates = {f"{config['name']}-{service}", f"{config['name']}_{service}"} & images
    if len(candidates) != 1:
        raise ReleaseError(f"{service}: unable to resolve one exact Compose image")
    return candidates.pop()


class Release:
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ReleaseError(
                "--revision must be the full 40-character pushed commit SHA"
            )
        self.root = root.resolve()
        self.revision = revision
        self.env = dict(
            os.environ, APP_REVISION=revision, EXPECTED_DATABASE_SCHEMA_REVISION=SCHEMA
        )
        self.directory = self.root / "tmp" / "traveller-whatsapp-release"
        self.manifest_path = self.directory / f"{revision}.json"
        self.pin_path = self.directory / f"{revision}.compose.json"
        self.phase = "preflight"
        self.compose: list[str] = []

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
            raise ReleaseError(
                f"{self.phase}: {' '.join(args[:3])} exited {result.returncode}"
            )
        return (result.stdout or "").strip()

    def dc(self, *args: str, pinned: bool = False, **kwargs: Any) -> str:
        override = ["-f", str(self.pin_path)] if pinned else []
        return self.run(*self.compose, *override, *args, **kwargs)

    def inspect(self, identifier: str, *, image: bool = False) -> dict[str, Any]:
        args = ("docker", "image", "inspect") if image else ("docker", "inspect")
        data = json.loads(self.run(*args, identifier))
        if (
            not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], dict)
        ):
            raise ReleaseError("Docker did not return one inspectable object")
        return data[0]

    def say(self, phase: str) -> None:
        self.phase = phase
        print(phase, flush=True)

    def preflight(self) -> dict[str, Any]:
        if self.run("git", "rev-parse", "HEAD") != self.revision:
            raise ReleaseError(
                "Checkout does not match --revision; pull the intended commit first"
            )
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
        if not (self.root / ".env").is_file():
            raise ReleaseError("The existing production .env is missing")
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
        config = json.loads(self.dc("config", "--format", "json"))
        if config.get("name") != project or not {*ACTIVATED, "nginx"} <= set(
            config.get("services", {})
        ):
            raise ReleaseError(
                "The resolved Compose project is missing required release services"
            )
        return config

    def config_fingerprint(self, config: dict[str, Any]) -> str:
        # The two intentional release variables are normalized before hashing .env.
        env_text = updated_environment((self.root / ".env").read_text(), self.revision)
        resolved = copy.deepcopy(config)
        for service, definition in resolved["services"].items():
            environment = definition.setdefault("environment", {})
            for key, value in {
                "APP_REVISION": self.revision,
                "EXPECTED_DATABASE_SCHEMA_REVISION": SCHEMA,
            }.items():
                if key in environment or service in (*WORKERS, "backend"):
                    environment[key] = value
        value = (
            json.dumps(resolved, sort_keys=True, separators=(",", ":"))
            + "\n"
            + env_text
        )
        return hashlib.sha256(value.encode()).hexdigest()

    def write_private(self, path: Path, data: str, *, exclusive: bool = False) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.directory.chmod(0o700)
        if exclusive:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(data)
            return
        descriptor, filename = tempfile.mkstemp(
            prefix=".traveller-release-", dir=path.parent
        )
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, "w") as output:
                output.write(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def verify_image(self, identifier: str, *, backend: bool) -> str:
        image = self.inspect(identifier, image=True)
        image_id = image.get("Id", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ReleaseError("Docker returned an invalid image ID")
        if backend:
            env = dict(
                value.split("=", 1)
                for value in image["Config"].get("Env", [])
                if "=" in value
            )
            revision = (image["Config"].get("Labels") or {}).get(
                "org.opencontainers.image.revision"
            )
            if env.get("APP_REVISION") != self.revision or revision != self.revision:
                raise ReleaseError(
                    "Built backend/worker image does not contain the intended revision"
                )
        return image_id

    def prepare(self) -> None:
        self.say("Checking the exact checkout and existing Compose project")
        config = self.preflight()
        fingerprint = self.config_fingerprint(config)
        references = set(self.dc("config", "--images").splitlines())
        refs = {
            service: image_reference(config, references, service)
            for service in ACTIVATED
        }
        if any(refs[service] != refs["worker"] for service in WORKERS):
            raise ReleaseError(
                "All seven workers and beat must share the configured worker image"
            )
        self.say(
            "Building backend, the shared worker image, and frontend; current containers stay running"
        )
        self.dc(
            "build",
            "--build-arg",
            f"APP_REVISION={self.revision}",
            "backend",
            "worker",
            "frontend",
            timeout=7200,
            stream=True,
        )
        images = {
            service: self.verify_image(refs[service], backend=service != "frontend")
            for service in ACTIVATED
        }
        # Recheck Git/environment after a potentially long build before recording it.
        after = self.preflight()
        if self.config_fingerprint(after) != fingerprint:
            raise ReleaseError(
                "Compose settings changed during the build; prepare again"
            )
        manifest = {
            "version": 1,
            "revision": self.revision,
            "schema": SCHEMA,
            "project": config["name"],
            "config_fingerprint": fingerprint,
            "images": images,
            "references": refs,
        }
        self.write_private(self.manifest_path, json.dumps(manifest, indent=2) + "\n")
        self.say(
            "PREPARED: images verified. Pause new uploads and message sends before activate."
        )

    def container(self, service: str) -> dict[str, Any]:
        ids = self.dc("ps", "--quiet", service).split()
        if len(ids) != 1:
            raise ReleaseError(f"{service}: expected exactly one running container")
        container = self.inspect(ids[0])
        labels = container.get("Config", {}).get("Labels") or {}
        if (
            not container.get("State", {}).get("Running")
            or labels.get(SERVICE_LABEL) != service
            or labels.get(PROJECT_LABEL) != self.compose[3]
        ):
            raise ReleaseError(
                f"{service}: running container identity does not match this project"
            )
        return container

    def worker_probe(self, *, idle: bool) -> None:
        nodes = set()
        for service, prefix in NODE_PREFIXES.items():
            hostname = self.container(service).get("Config", {}).get("Hostname")
            if not isinstance(hostname, str) or not hostname:
                raise ReleaseError(f"{service}: worker hostname is missing")
            nodes.add(f"{prefix}@{hostname}")
        output = self.dc(
            "exec",
            "-T",
            "worker",
            "python",
            "-c",
            CONTROL_PROBE,
            json.dumps(sorted(nodes)),
            "idle" if idle else "ping",
            timeout=55,
        )
        payloads = [
            line[len(PROBE_MARKER) :]
            for line in output.splitlines()
            if line.startswith(PROBE_MARKER)
        ]
        if len(payloads) != 1:
            raise ReleaseError("Worker probe did not return one complete result")
        validate_worker_probe(json.loads(payloads[0]), nodes, idle=idle)

    def verify_containers(
        self, services: tuple[str, ...], images: dict[str, str]
    ) -> None:
        for service in services:
            container = self.container(service)
            if container.get("Image") != images[service]:
                raise ReleaseError(
                    f"{service}: running image is not the prepared image ID"
                )
            if service != "frontend":
                env = dict(
                    item.split("=", 1)
                    for item in container["Config"].get("Env", [])
                    if "=" in item
                )
                if (
                    env.get("APP_REVISION") != self.revision
                    or env.get("EXPECTED_DATABASE_SCHEMA_REVISION") != SCHEMA
                ):
                    raise ReleaseError(
                        f"{service}: running revision/schema setting is incorrect"
                    )

    def schema(self) -> str:
        output = self.dc(
            "run",
            "--rm",
            "--no-deps",
            "backend",
            "alembic",
            "current",
            pinned=True,
            timeout=180,
        )
        matches = re.findall(
            r"^(009\d_[A-Za-z0-9_]+)(?:\s|$)", output, flags=re.MULTILINE
        )
        if len(matches) != 1:
            raise ReleaseError(
                "Could not verify the database's single Alembic revision"
            )
        return matches[0]

    def activate(self) -> None:
        self.say(
            "Checking prepared image IDs, checkout, and unchanged production configuration"
        )
        config = self.preflight()
        if not self.manifest_path.is_file():
            raise ReleaseError(
                "No prepared release exists for this revision; run prepare first"
            )
        manifest = json.loads(self.manifest_path.read_text())
        if (
            manifest.get("version") != 1
            or manifest.get("revision") != self.revision
            or manifest.get("schema") != SCHEMA
            or manifest.get("project") != config["name"]
            or manifest.get("config_fingerprint") != self.config_fingerprint(config)
        ):
            raise ReleaseError(
                "Prepared release does not match the checkout/settings; run prepare again"
            )
        images = manifest.get("images", {})
        refs = manifest.get("references", {})
        if set(images) != set(ACTIVATED) or set(refs) != set(ACTIVATED):
            raise ReleaseError("Prepared image manifest is incomplete")
        for service in ACTIVATED:
            if (
                self.verify_image(refs[service], backend=service != "frontend")
                != images[service]
            ):
                raise ReleaseError(
                    f"{service}: image tag changed after prepare; run prepare again"
                )
        self.say(
            "Checking all seven workers are empty for active, reserved, and scheduled tasks"
        )
        self.worker_probe(idle=True)
        self.container("email-beat")
        self.write_private(
            self.pin_path,
            json.dumps(
                {
                    "services": {
                        service: {"image": images[service], "pull_policy": "never"}
                        for service in ACTIVATED
                    }
                },
                indent=2,
            )
            + "\n",
        )
        env_path = self.root / ".env"
        original = env_path.read_text()
        backup = self.directory / f"{self.revision}.env.backup"
        if not backup.exists():
            self.write_private(backup, original, exclusive=True)
        self.write_private(env_path, updated_environment(original, self.revision))
        self.say("Applying additive migration 0093 from the prepared backend image")
        if self.schema() not in {PREVIOUS_SCHEMA, SCHEMA}:
            raise ReleaseError(
                "This release requires database revision 0092 or 0093; no broader migration was attempted"
            )
        self.dc(
            "run",
            "--rm",
            "--no-deps",
            "backend",
            "alembic",
            "upgrade",
            SCHEMA,
            pinned=True,
            timeout=600,
            stream=True,
        )
        if self.schema() != SCHEMA:
            raise ReleaseError("Migration 0093 was not confirmed")
        # No worker is recreated on stale pre-migration idle evidence.
        self.worker_probe(idle=True)
        options = (
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--timeout",
            "60",
            "--wait",
            "--wait-timeout",
            "180",
        )
        self.say("Activating all seven workers and beat before the web services")
        self.dc(*options, *WORKERS, pinned=True, timeout=720, stream=True)
        self.verify_containers(WORKERS, images)
        for attempt in range(6):
            try:
                self.worker_probe(idle=False)
                break
            except ReleaseError:
                if attempt == 5:
                    raise
                time.sleep(5)
        self.say("Activating and verifying backend, then frontend")
        self.dc(*options, "backend", pinned=True, timeout=240, stream=True)
        self.verify_containers(("backend",), images)
        self.dc("exec", "-T", "backend", "python", "-c", READY_PROBE)
        self.dc(*options, "frontend", pinned=True, timeout=240, stream=True)
        self.verify_containers(("frontend",), images)
        self.say("Checking Nginx and public API/frontend readiness")
        self.dc("exec", "-T", "nginx", "nginx", "-t", stream=True)
        self.dc("exec", "-T", "nginx", "nginx", "-s", "reload", stream=True)
        for route in ("/api/v1/health/ready", "/"):
            status = self.run(
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-redirs",
                "5",
                "--max-time",
                "30",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                PUBLIC_URL + route,
            )
            if status != "200":
                raise ReleaseError(f"Public {route} did not return HTTP 200")
        self.verify_containers(ACTIVATED, images)
        self.dc("ps", stream=True)
        self.say(
            f"RELEASE VERIFIED: {self.revision}; schema {SCHEMA}; backend, frontend, seven workers and beat."
        )


@contextlib.contextmanager
def release_lock(directory: Path):
    # Linux VPS advisory lock is released by the kernel even if the helper is interrupted.
    import fcntl

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        directory.chmod(0o700)
    with (directory / "release.lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ReleaseError("Another traveller release helper is running") from error
        yield


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "activate"))
    parser.add_argument("--revision", required=True, help="Full pushed main commit SHA")
    parser.add_argument(
        "--traffic-paused",
        action="store_true",
        help="Confirm new uploads/message sends are paused for activation",
    )
    args = parser.parse_args()
    try:
        release = Release(args.revision)
        if args.mode == "activate" and not args.traffic_paused:
            raise ReleaseError(
                "Pause new uploads and message sends, then use activate --traffic-paused"
            )
        with release_lock(release.directory):
            getattr(release, args.mode)()
    except (ReleaseError, ValueError, OSError) as error:
        print(
            f"STOPPED: {error}. No automatic rollback, Git changes, or queue purge was attempted.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
