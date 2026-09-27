"""Historical worker-only recovery helper for the 0092 deployment.

Retained from backup for reference; review its fixed schema, service list and
two-file Compose assumptions before using it for any current deployment.
Original usage on the VPS: python3 scripts/recover_worker_deployment.py check|apply
No database migrations, image builds, web restarts, queue purges, or force kills.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROBE = Path(__file__).with_name("worker_shutdown_probe.py").read_text()
SERVICES = (
    "email-beat", "worker", "email-worker", "email-ai-worker",
    "extraction-worker", "verification-worker", "visa-ai-worker", "my-photos-worker",
)
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
SCHEMA = "0092_whatsapp_matching_fields"


def run(*args: str, stdin: str | None = None, timeout: int = 60) -> str:
    result = subprocess.run(
        args, cwd=ROOT, input=stdin, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode:
        # Do not dump rendered configuration or inspection JSON (can contain secrets).
        raise RuntimeError(f"{' '.join(args[:4])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def inspect(identifier: str) -> dict[str, Any]:
    return json.loads(run("docker", "inspect", identifier))[0]


def environment(config: dict[str, Any]) -> dict[str, str]:
    return dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)


def selected_containers(
    containers: list[dict[str, Any]], project: str,
) -> list[dict[str, Any]]:
    result = []
    running: set[str] = set()
    for container in containers:
        labels = container["Config"].get("Labels") or {}
        service = labels.get(SERVICE_LABEL)
        if labels.get(PROJECT_LABEL) != project or service not in SERVICES:
            continue
        if str(labels.get("com.docker.compose.oneoff", "False")).lower() == "true":
            continue
        state = container["State"]["Status"]
        if state not in {"running", "created", "exited"}:
            raise RuntimeError(f"{service} is {state}; resolve that state before recovery")
        if state == "running":
            if service in running:
                raise RuntimeError(f"Multiple running containers for {service}; refusing rollout")
            running.add(service)
        result.append(container)
    if not any(c["Config"]["Labels"][SERVICE_LABEL] == "worker" for c in result):
        raise RuntimeError("Main worker is missing; refusing to guess the deployment scope")
    return result


class Recovery:
    def __init__(self) -> None:
        backend = inspect("passdetection-backend")
        if backend["State"]["Status"] != "running":
            raise RuntimeError("Restore the website backend first")
        self.web_ids = {name: inspect(name)["Id"] for name in (
            "passdetection-backend", "passdetection-frontend", "passdetection-nginx",
        )}
        self.project = backend["Config"]["Labels"][PROJECT_LABEL]
        self.compose = [
            "docker", "compose", "-p", self.project,
            "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
        ]
        self.revision = environment(backend["Config"]).get("APP_REVISION", "")
        if not re.fullmatch(r"[0-9a-f]{40}", self.revision):
            raise RuntimeError("Backend application revision is unknown")
        image = json.loads(run("docker", "image", "inspect", "passdetection-backend:latest"))[0]
        self.image_id = image["Id"]
        if environment(image["Config"]).get("APP_REVISION") != self.revision:
            raise RuntimeError("Built worker image does not match the restored backend revision")
        # This helper reuses an image only when the checkout has identical application code.
        run("git", "diff", "--quiet", self.revision, "--", "backend")
        config = json.loads(run(*self.compose, "config", "--format", "json"))
        ids = run("docker", "ps", "-aq", "--filter", f"label={PROJECT_LABEL}={self.project}").split()
        containers = json.loads(run("docker", "inspect", *ids)) if ids else []
        self.containers = selected_containers(containers, self.project)
        present = {c["Config"]["Labels"][SERVICE_LABEL] for c in self.containers}
        self.services = [service for service in SERVICES if service in present]
        for service in self.services:
            definition = config["services"][service]
            command = definition.get("command", [])
            command = " ".join(command) if isinstance(command, list) else command
            if not command or "exec celery -A " not in command:
                raise RuntimeError(f"{service} is missing the exec shutdown fix; pull main first")
            settings = definition.get("environment", {})
            if settings.get("APP_REVISION", self.revision) != self.revision:
                raise RuntimeError(f"{service} APP_REVISION differs from the prepared image")
            if settings.get("EXPECTED_DATABASE_SCHEMA_REVISION") != SCHEMA:
                raise RuntimeError(f"{service} database schema setting is not {SCHEMA}")
            configured_image = json.loads(run("docker", "image", "inspect", definition["image"]))[0]
            if configured_image["Id"] != self.image_id:
                raise RuntimeError(f"{service} is configured to use a different image")
        self.processes = {}
        for container in self.containers:
            service = container["Config"]["Labels"][SERVICE_LABEL]
            state = container["State"]["Status"]
            print(f"{service}: {container['Name'].lstrip('/')} — {state}", flush=True)
            if state == "running":
                self.processes[container["Id"]] = self.probe(container, "check")
        self.changed: list[dict[str, Any]] = []
        self.converging = False

    def probe(self, container: dict[str, Any], mode: str) -> dict[str, Any]:
        service = container["Config"]["Labels"][SERVICE_LABEL]
        args = ["docker", "exec", "-i", container["Id"], "python", "-", mode,
                "beat" if service == "email-beat" else "worker"]
        if mode == "stop":
            args.append(json.dumps(self.processes[container["Id"]]))
        return json.loads(run(*args, stdin=PROBE, timeout=20))

    def stop(self, container: dict[str, Any]) -> None:
        identifier = container["Id"]
        if inspect(identifier)["State"]["Status"] != "running":
            return
        # A direct SIGTERM otherwise allows restart: unless-stopped to relaunch the old worker.
        self.changed.append(container)
        run("docker", "update", "--restart=no", identifier)
        print(f"Warm shutdown: {container['Config']['Labels'][SERVICE_LABEL]}", flush=True)
        try:
            self.probe(container, "stop")
        except (RuntimeError, json.JSONDecodeError):
            # Successful main-process exit may also end docker exec before its stdout flushes.
            if inspect(identifier)["State"]["Status"] != "exited":
                raise

    def wait_stopped(self, containers: list[dict[str, Any]], seconds: int) -> None:
        deadline = time.monotonic() + seconds
        while True:
            waiting = []
            for container in containers:
                state = inspect(container["Id"])["State"]["Status"]
                if state == "running":
                    waiting.append(container["Config"]["Labels"][SERVICE_LABEL])
                elif state != "exited":
                    raise RuntimeError(f"Unexpected state during drain: {state}")
            if not waiting:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("Drain deadline reached; no tasks were force-killed")
            print("Finishing current tasks: " + ", ".join(waiting), flush=True)
            time.sleep(5)

    def rollback_drain(self) -> None:
        for container in reversed(self.changed):
            identifier = container["Id"]
            policy = container["HostConfig"]["RestartPolicy"]
            name = policy["Name"] or "no"
            if name == "on-failure" and policy.get("MaximumRetryCount"):
                name += f":{policy['MaximumRetryCount']}"
            try:
                run("docker", "update", f"--restart={name}", identifier)
                if inspect(identifier)["State"]["Status"] == "exited":
                    run("docker", "start", identifier)
                print(f"Restored previous restart policy: {container['Name']}", flush=True)
            except Exception as exc:
                print(f"Recovery needed for {identifier[:12]}: {exc}", file=sys.stderr)

    def apply(self) -> None:
        try:
            schedulers = [c for c in self.containers if c["Id"] in self.processes
                          and c["Config"]["Labels"][SERVICE_LABEL] == "email-beat"]
            workers = [c for c in self.containers if c["Id"] in self.processes
                       and c["Config"]["Labels"][SERVICE_LABEL] != "email-beat"]
            # Stop periodic task production before draining consumers.
            for container in schedulers:
                self.stop(container)
            self.wait_stopped(schedulers, 90)
            for container in workers:
                self.stop(container)
            self.wait_stopped(workers, 900)
            for container in self.containers:
                if container["State"]["Status"] != "created":
                    continue
                current = inspect(container["Id"])
                if current["State"]["Status"] != "created":
                    raise RuntimeError("Replacement state changed; refusing cleanup")
                print(f"Removing unused, never-started replacement: {current['Name']}", flush=True)
                run("docker", "rm", container["Id"])
            # From here Compose can remove old containers; do not restart stale IDs on failure.
            self.converging = True
            command = [*self.compose, "up", "-d", "--no-deps", "--no-build",
                       "--timeout", "30", "--wait", "--wait-timeout", "180", *self.services]
            print("Starting updated workers only; website containers are untouched.", flush=True)
            subprocess.run(command, cwd=ROOT, check=True, timeout=300)
            self.verify()
        except BaseException:
            if not self.converging:
                self.rollback_drain()
            raise

    def verify(self) -> None:
        for service in self.services:
            ids = run(*self.compose, "ps", "-a", "-q", service).split()
            if len(ids) != 1:
                raise RuntimeError(f"Expected exactly one container for {service}")
            container = inspect(ids[0])
            if container["State"].get("Health", {}).get("Status") != "healthy":
                raise RuntimeError(f"{service} is not healthy")
            if container["Image"] != self.image_id:
                raise RuntimeError(f"{service} is not running the prepared image")
            if environment(container["Config"]).get("APP_REVISION") != self.revision:
                raise RuntimeError(f"{service} application revision mismatch")
            if self.probe(container, "check")["pid"] != 1:
                raise RuntimeError(f"{service} Celery is not PID 1")
            print(f"Verified {service}: healthy, revision {self.revision[:7]}, Celery PID 1", flush=True)
        for name, identifier in self.web_ids.items():
            current = inspect(name)
            if current["Id"] != identifier or current["State"]["Status"] != "running":
                raise RuntimeError(f"Web container changed during recovery: {name}")
        print(run("docker", "exec", "passdetection-backend", "python", "-c",
                  "import urllib.request; print(urllib.request.urlopen("
                  "'http://127.0.0.1:8000/api/v1/health/ready', timeout=10).read().decode())"))
        print("Worker rollout complete. Website containers were not restarted.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "apply"))
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Run this helper on the Linux VPS, not your development computer")
    import fcntl

    # Project-local advisory lock prevents two copies of this helper from draining together.
    lock_path = ROOT / ".git" / "worker-recovery.lock"
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            recovery = Recovery()
            print(f"Prepared application image: {recovery.revision}", flush=True)
            if args.mode == "apply":
                recovery.apply()
            else:
                print("Preflight passed. No containers were changed. Run the apply command next.")
        except (Exception, KeyboardInterrupt) as exc:
            print(f"STOPPED: {exc or 'interrupted'}", file=sys.stderr)
            print("Do not force-kill or purge queues. Paste this output for diagnosis.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
