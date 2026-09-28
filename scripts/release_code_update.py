"""Promote signed, same-schema images while retaining a serving web pair.

Run from the trusted candidate checkout; --root is the existing deployment.
Workers are drained and paused to admit a second full-size web pair on KVM4.
No migration, storage transition, infrastructure recreation or test send occurs.
The receipt supports recovery after an interrupted invocation. Ordinary failures
restore the previous app images; database and object data are never restored.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import ipaddress
import json
import os
import re
import signal
import time
import uuid
from pathlib import Path
from typing import Any

from release_artifacts import verify_manifest
from release_manifest import load_release_manifest, verify_rendered_release
from release_reliability import ReliabilityRelease
from image_runtime_policy import WORKER_COMMANDS, validate_process_isolation
from release_resource_profile import validate_local_swap_free_host, validate_profile
from release_traveller_whatsapp import (
    CONTROL_PROBE, PROJECT_LABEL, PROBE_MARKER, ROOT, SERVICE_LABEL,
    ReleaseError, release_lock, updated_environment, validate_worker_probe,
)
from verify_deployment_resource_budget import _memory_bytes

INFRA = ("db", "redis", "redis-broker", "redis-realtime", "redis-cache", "minio", "clamav", "nginx", "metrics-exporter")
WEB = ("backend", "frontend")
CORE_CAPABILITIES = {"request_protection", "object_storage", "document_ingestion", "database_schema", "mobile_realtime"}
# A same-schema rollback is insufficient if configuration, message serialization,
# persistent entities, or dependencies have changed. Those need another plan.
COMPATIBILITY_PATHS = (
    "docker-compose*.yml", "nginx", "backend/alembic", "backend/Dockerfile", "frontend/Dockerfile",
    "backend/requirements*", "frontend/package*.json", "backend/app/core/config",
    "backend/app/domain/entities", "backend/app/infrastructure/database",
    "backend/app/infrastructure/processing/celery_app.py", "backend/app/infrastructure/processing/task_contracts.py",
    "backend/app/infrastructure/storage", "tooling/deployment-profiles", "tooling/database-deployment-budget.json",
)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def environment(container: dict) -> dict[str, str]:
    return dict(item.split("=", 1) for item in container["Config"].get("Env", []) if "=" in item)


def task_contract(source: str) -> dict[str, str]:
    contracts = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [item for item in node.decorator_list if isinstance(item, ast.Call)
                          and ((isinstance(item.func, ast.Attribute) and item.func.attr == "task")
                               or (isinstance(item.func, ast.Name) and item.func.id == "shared_task"))]
            if decorators:
                contracts[node.name] = ast.dump(node.args) + ":" + ":".join(ast.dump(item) for item in decorators)
    return contracts


def web_configuration(original: str, addresses: dict[str, str]) -> str:
    """Only replace the two reviewed upstream endpoints; preserve all controls."""
    value = original
    for service, port in (("backend", 8000), ("frontend", 3000)):
        address = str(ipaddress.IPv4Address(addresses[service]))
        pattern = rf"(upstream\s+{service}\s*\{{\s*)server\s+{service}:{port};"
        value, count = re.subn(pattern, rf"\g<1>server {address}:{port};", value)
        if count != 1:
            raise ReleaseError("Nginx upstream structure differs from the reviewed code-update contract")
    return value


def validate_readiness(payload: dict, revision: str, *, full: bool) -> None:
    if payload.get("revision") != revision or payload.get("checks", {}).get("database") != "ok":
        raise ReleaseError("Web probe revision or database differs from the candidate")
    capabilities = payload.get("capabilities", {})
    if not CORE_CAPABILITIES <= capabilities.keys():
        raise ReleaseError("Web probe omitted a required core capability")
    required = {name for name, entry in capabilities.items() if entry.get("required")} if full else CORE_CAPABILITIES
    if any(not capabilities[name].get("available") for name in required):
        raise ReleaseError("A required web capability is unavailable")
    if full and payload.get("status") != "ready":
        raise ReleaseError("All-worker readiness is not established")


def validate_capacity(running: list[dict], paused_ids: set[str], web_caps: int, host_bytes: int) -> dict[str, int]:
    caps = []
    for item in running:
        memory = item.get("HostConfig", {}).get("Memory", 0)
        if not isinstance(memory, int) or memory <= 0:
            raise ReleaseError("Every concurrent container needs a finite inspected memory cap")
        caps.append((item["Id"], memory))
    steady = sum(memory for _, memory in caps)
    staging = sum(memory for identifier, memory in caps if identifier not in paused_ids) + web_caps
    if max(steady, staging) + 2 * 1024**3 > host_bytes:
        raise ReleaseError("Serving web overlap exceeds physical memory plus the fixed 2 GiB host reserve")
    return {"steady_bytes": steady, "web_overlap_bytes": staging, "host_bytes": host_bytes, "reserve_bytes": 2 * 1024**3}


class CodeUpdate(ReliabilityRelease):
    def __init__(self, revision: str, root: Path, artifact: Path, *, source: Path = ROOT) -> None:
        contract = load_release_manifest(source / "backend/app/core/config/release_manifest.json")
        self.release_contract = contract
        super().__init__(revision, root, expected_schema=contract["schema_revision"],
                         previous_schema=contract["schema_revision"], directory_name="code-updates",
                         worker_nodes=contract["worker_nodes"], preserve_release_artifacts=True)
        self.source = source.resolve()
        self.artifact = artifact.resolve()
        self.receipt_path = self.directory / f"{revision}.state.json"
        self.recovery_pin = self.directory / f"{revision}.previous.compose.json"
        self.original_env = self.directory / f"{revision}.env.backup"
        self.original_nginx = self.directory / f"{revision}.nginx.backup"
        self.record: dict[str, Any] = {}

    def save(self, phase: str) -> None:
        self.record["phase"] = phase
        self.write_private(self.receipt_path, json.dumps(self.record, indent=2) + "\n")
        self.say(f"Code update: {phase}")

    def optional_existing(self, service: str) -> dict | None:
        ids = self.run("docker", "ps", "-aq", "--filter", f"label={PROJECT_LABEL}={self.compose[3]}",
                       "--filter", f"label={SERVICE_LABEL}={service}",
                       "--filter", "label=com.docker.compose.oneoff=False").split()
        if not ids:
            return None
        if len(ids) != 1:
            raise ReleaseError(f"{service}: expected one normal Compose container")
        item = self.inspect(ids[0])
        if Path(item["Config"]["Labels"].get("com.docker.compose.project.working_dir", "")).resolve() != self.root:
            raise ReleaseError("Compose working-directory identity changed")
        return item

    def existing(self, service: str) -> dict:
        item = self.optional_existing(service)
        if item is None:
            raise ReleaseError(f"{service}: expected one normal Compose container")
        return item

    def container(self, service: str) -> dict:
        item = self.existing(service)
        if not item["State"].get("Running"):
            raise ReleaseError(f"{service}: container is not running")
        return item

    def discover(self) -> None:
        ids = self.run("docker", "ps", "-q", "--filter", f"label={SERVICE_LABEL}=backend",
                       "--filter", "label=com.docker.compose.oneoff=False").split()
        matches = [self.inspect(item) for item in ids]
        matches = [item for item in matches if Path(item["Config"]["Labels"].get(
            "com.docker.compose.project.working_dir", "")).resolve() == self.root]
        if len(matches) != 1:
            raise ReleaseError("Exactly one live backend in the intended root is required")
        labels = matches[0]["Config"]["Labels"]
        files = [str(Path(value).resolve()) for value in labels["com.docker.compose.project.config_files"].split(",")]
        required = {str(self.root / name) for name in ("docker-compose.yml", "docker-compose.prod.yml", "docker-compose.storage-production.yml", "docker-compose.kvm4.yml", "tmp/current-release/storage-go-memory.json")}
        if not required <= set(files):
            raise ReleaseError("The live KVM4/storage overlays are incomplete")
        for value in files:
            path = Path(value)
            if not path.is_file() or path.is_symlink() or not path.is_relative_to(self.root):
                raise ReleaseError("Every active Compose file must be a regular file within this root")
        self.compose = ["docker", "compose", "-p", labels[PROJECT_LABEL]]
        for value in files:
            self.compose.extend(["-f", value])
        self.compose.extend(["--profile", "maintenance"])
        self.record["compose"] = self.compose
        self.record["compose_sha256"] = {value: hashlib.sha256(Path(value).read_bytes()).hexdigest() for value in files}

    def schema(self) -> str:
        return self.run("docker", "exec", self.container("db")["Id"], "sh", "-c",
                        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM public.alembic_version"')

    def unchanged_infrastructure(self) -> None:
        for name, identifier in self.record["infra"].items():
            if self.container(name)["Id"] != identifier:
                raise ReleaseError(f"{name}: persistent infrastructure identity changed")
        if self.schema() != self.expected_schema:
            raise ReleaseError("The live database schema changed")

    def verify_binding(self) -> None:
        for filename, expected in self.record["compose_sha256"].items():
            if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != expected:
                raise ReleaseError("A bound Compose overlay changed after preparation")
        original = self.original_env.read_text()
        if hashlib.sha256(self.original_env.read_bytes()).hexdigest() != self.record["original_env_sha256"]:
            raise ReleaseError("Protected environment backup changed")
        if (self.root / ".env").read_text() not in {original, updated_environment(original, self.revision, self.expected_schema)}:
            raise ReleaseError("Production environment changed after preparation")
        if hashlib.sha256(self.original_nginx.read_bytes()).hexdigest() != self.record["original_nginx_sha256"]:
            raise ReleaseError("Protected Nginx backup changed")

    def compatibility(self, previous: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", previous):
            raise ReleaseError("Current source revision is missing")
        if self.run("git", "-C", str(self.source), "rev-parse", "HEAD") != self.revision:
            raise ReleaseError("The release helper source does not match the signed revision")
        self.run("git", "-C", str(self.source), "diff", "--quiet", "HEAD", "--")
        self.run("git", "merge-base", "--is-ancestor", previous, self.revision)
        self.run("git", "merge-base", "--is-ancestor", self.revision, "origin/main")
        changed = self.run("git", "diff", "--name-only", previous, self.revision, "--", *COMPATIBILITY_PATHS)
        if changed:
            raise ReleaseError("Same-schema recovery refuses deployment/configuration/persistence/task-contract changes")
        self.run("git", "diff", "--quiet", "HEAD", "--", *COMPATIBILITY_PATHS)
        changed_app = self.run("git", "diff", "--name-only", previous, self.revision, "--", "backend/app").splitlines()
        for path in changed_app:
            if not path.endswith(".py"):
                continue
            old_files = self.run("git", "ls-tree", "--name-only", previous, "--", path).splitlines()
            new_files = self.run("git", "ls-tree", "--name-only", self.revision, "--", path).splitlines()
            old = self.run("git", "show", f"{previous}:{path}") if old_files else ""
            new = self.run("git", "show", f"{self.revision}:{path}") if new_files else ""
            if task_contract(old) != task_contract(new):
                raise ReleaseError("Queued task declaration/signature changed; separate compatibility qualification required")

    def live_capacity(self, config: dict, *, workers_paused: bool = False) -> None:
        endpoint = self.run("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
        if self.env.get("DOCKER_HOST") or self.env.get("DOCKER_CONTEXT"):
            raise ReleaseError("Code updates require the default local Docker context")
        validate_local_swap_free_host(endpoint)
        ids = self.run("docker", "ps", "-q").split()
        running = [self.inspect(identifier) for identifier in ids]
        paused = {item["Id"] for name in self.workers if (item := self.optional_existing(name)) is not None}
        if workers_paused and any(item["Id"] in paused for item in running):
            raise ReleaseError("A paused worker is still running")
        total = int(re.search(r"^MemTotal:\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M)[1]) * 1024
        web_caps = sum(_memory_bytes(config["services"][name]["mem_limit"]) for name in WEB)
        self.record["capacity"] = validate_capacity(running, paused, web_caps, total)
        env = config["services"]["backend"]["environment"]
        transient_pools = 2 * int(env["WEB_CONCURRENCY"]) * (int(env["POSTGRES_API_POOL_SIZE"]) + int(env["POSTGRES_API_MAX_OVERFLOW"]))
        if transient_pools + int(env["POSTGRES_RESERVED_CONNECTIONS"]) > int(env["POSTGRES_SERVER_MAX_CONNECTIONS"]):
            raise ReleaseError("Two web pairs exceed PostgreSQL capacity even with workers paused")
        maximum = self.run("docker", "exec", self.container("db")["Id"], "sh", "-c",
                           'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SHOW max_connections"')
        if int(maximum) != int(env["POSTGRES_SERVER_MAX_CONNECTIONS"]):
            raise ReleaseError("Inspected PostgreSQL connection ceiling differs from the reviewed configuration")
        self.record["transient_api_pool_claim"] = transient_pools

    def prepare(self) -> dict:
        self.record = {"version": 1, "revision": self.revision, "root": str(self.root), "candidates": {}, "original_recreated": False}
        self.discover()
        old_revision = environment(self.container("backend")).get("APP_REVISION", "")
        self.compatibility(old_revision)
        if self.schema() != self.expected_schema:
            raise ReleaseError("Code-only deployment requires the already-current database schema")
        manifest = verify_manifest(self.artifact, self.revision, pull=True, enforce_current_policy=True)
        if manifest["schema"] != self.expected_schema:
            raise ReleaseError("Signed artifact schema differs from the live schema")
        self.run("git", "fetch", "origin", "main", timeout=180)
        if self.run("git", "rev-parse", "origin/main") != self.revision:
            raise ReleaseError("The signed candidate was superseded on main before deployment")
        config = json.loads(self.dc("config", "--format", "json"))
        verify_rendered_release(config, self.release_contract)
        validate_process_isolation(config["services"])
        my_photos_jobs = self.run("docker", "exec", self.container("db")["Id"], "sh", "-c",
                                 'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM public.my_photo_jobs"')
        validate_profile(config, json.loads((self.source / "tooling/deployment-profiles/kvm4.json").read_text()),
                         activation=True, my_photos_jobs=int(my_photos_jobs),
                         live_backend_environment=environment(self.container("backend")))
        self.record.update(previous_revision=old_revision,
                           infra={name: self.container(name)["Id"] for name in INFRA},
                           original={name: {"id": self.container(name)["Id"], "image": self.container(name)["Image"]} for name in self.activated_services},
                           images={name: manifest["images"]["frontend" if name == "frontend" else "backend"]["local_image_id"] for name in self.activated_services})
        self.record["serving"] = {name: self.record["original"][name]["id"] for name in WEB}
        self.record["nginx_bindings"] = {}
        self._verify_live_database_target(self.container("backend"), self.container("db"))
        for name in self.activated_services:
            current = self.container(name)
            expected = config["services"][name]
            if current["HostConfig"]["Memory"] != _memory_bytes(expected["mem_limit"]):
                raise ReleaseError("Live memory caps differ from the unchanged Compose contract")
            if name != "frontend" and environment(current).get("APP_REVISION") != old_revision:
                raise ReleaseError("Current application services have mixed revisions")
            if name != "frontend":
                configured = expected.get("environment", {})
                actual = environment(current)
                if any(str(value) != actual.get(key) for key, value in configured.items()
                       if key not in {"APP_REVISION", "EXPECTED_DATABASE_SCHEMA_REVISION"}):
                    raise ReleaseError("Rendered runtime environment differs from the serving application")
        self.live_capacity(config)
        nginx_path = self.root / "nginx/nginx.conf"
        mount = [item for item in self.container("nginx")["Mounts"] if item["Destination"] == "/etc/nginx/nginx.conf"]
        if len(mount) != 1 or Path(mount[0]["Source"]).resolve() != nginx_path or nginx_path.is_symlink():
            raise ReleaseError("Nginx must bind the reviewed regular configuration file")
        web_configuration(nginx_path.read_text(), {"backend": "127.0.0.1", "frontend": "127.0.0.1"})
        self.write_private(self.original_nginx, nginx_path.read_text())
        self.write_private(self.original_env, (self.root / ".env").read_text())
        self.write_private(self.recovery_pin, json.dumps({"services": self.pinned_services({name: item["image"] for name, item in self.record["original"].items()})}))
        self.write_private(self.pin_path, json.dumps({"services": self.pinned_services(self.record["images"])}))
        self.record["original_env_sha256"] = hashlib.sha256(self.original_env.read_bytes()).hexdigest()
        self.record["original_nginx_sha256"] = hashlib.sha256(self.original_nginx.read_bytes()).hexdigest()
        self.probe(self.container("backend")["Id"], "backend", old_revision, full=True)
        self.prepare_recovery(config)
        self.before_migration(self.expected_schema)  # Same-schema branch: fresh verified backup only.
        self.save("prepared")
        return config

    def worker_control(self, code: str, *args: str) -> str:
        return self.run("docker", "exec", self.container("worker")["Id"], "python", "-c", code, *args, timeout=90)

    def pause_workers(self) -> None:
        self.verify_binding()
        self.save("pausing-workers")
        current = {name: item for name in self.workers if (item := self.optional_existing(name)) is not None}
        if not self.record.get("original_recreated") and len(current) != len(self.workers):
            raise ReleaseError("Worker inventory changed before the initial drain")
        if "email-beat" in current:
            self.run("docker", "stop", "--time", "60", current["email-beat"]["Id"], timeout=90)
        running = {name: item for name, item in current.items() if name in self.node_prefixes and item["State"].get("Running")}
        if not running:
            self.save("workers-paused")
            return
        control_id = next(iter(running.values()))["Id"]
        nodes = {f"{self.node_prefixes[name]}@{item['Config']['Hostname']}" for name, item in running.items()}
        cancel = """
import json,sys
from app.infrastructure.processing.celery_app import celery_app
nodes=json.loads(sys.argv[1]); queues=celery_app.control.inspect(destination=nodes,timeout=10).active_queues()
assert isinstance(queues,dict) and set(queues)==set(nodes), 'Incomplete consumer inventory'
for node,entries in queues.items():
 for entry in entries:
  replies=celery_app.control.cancel_consumer(entry['name'],destination=[node],reply=True,timeout=10)
  assert replies and any(node in value and 'ok' in value[node] for value in replies), 'Consumer cancellation not acknowledged'
"""
        self.run("docker", "exec", control_id, "python", "-c", cancel, json.dumps(sorted(nodes)), timeout=150)
        for attempt in range(60):
            output = self.run("docker", "exec", control_id, "python", "-c", CONTROL_PROBE, json.dumps(sorted(nodes)), "idle", timeout=90)
            payloads = [value[len(PROBE_MARKER):] for value in output.splitlines() if value.startswith(PROBE_MARKER)]
            try:
                if len(payloads) != 1:
                    raise ReleaseError("Incomplete drain response")
                validate_worker_probe(json.loads(payloads[0]), nodes, idle=True, expected_count=len(nodes))
                break
            except ReleaseError:
                if attempt == 59:
                    raise
                time.sleep(2)
        self.run("docker", "stop", "--time", "60", *(item["Id"] for item in running.values()), timeout=150)
        if any(item["State"].get("Running") for name in self.workers if (item := self.optional_existing(name)) is not None):
            raise ReleaseError("A consumer did not stop after the drain")
        self.save("workers-paused")

    def probe(self, identifier: str, service: str, revision: str, *, full: bool = False) -> None:
        if service == "frontend":
            script = "Promise.all(['/login','/assets/upload-samples/visa-photo.png'].map(async p=>{const r=await fetch('http://127.0.0.1:3000'+p);if(r.status!==200)throw Error('frontend probe failed')})).catch(()=>process.exit(1))"
            self.run("docker", "exec", identifier, "node", "-e", script, timeout=25)
            return
        code = """
import json,urllib.request,urllib.error
try:
 response=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=15)
except urllib.error.HTTPError as error:
 response=error
print(json.dumps(json.load(response)))
"""
        validate_readiness(json.loads(self.run("docker", "exec", identifier, "python", "-c", code, timeout=25)), revision, full=full)

    def wait_web(self, identifiers: dict[str, str], revision: str, *, full: bool = False) -> None:
        for attempt in range(45):
            try:
                for name, identifier in identifiers.items():
                    self.probe(identifier, name, revision, full=full)
                return
            except ReleaseError:
                if attempt == 44:
                    raise
                time.sleep(2)

    def start_candidates(self, config: dict) -> None:
        self.live_capacity(config, workers_paused=True)
        self.save("starting-candidates")
        for name in WEB:
            container_name = f"passdetection-stage-{self.revision[:12]}-{name}-{uuid.uuid4().hex[:8]}"
            self.record["candidates"][name] = container_name
            self.save("starting-candidates")
            # Compose run has no --no-build flag. A verified existing immutable
            # image plus pull=never and no --build prevents a replacement build.
            self.dc("run", "--no-deps", "--pull", "never", "-d", "--name", container_name, name, pinned=True, timeout=180)
            candidate = self.inspect(container_name)
            if candidate["Image"] != self.record["images"][name] or candidate["HostConfig"].get("PortBindings"):
                raise ReleaseError("Candidate image differs or publishes an unexpected host port")
            if any(name in (entry.get("Aliases") or []) for entry in candidate["NetworkSettings"]["Networks"].values()):
                raise ReleaseError("Candidate unexpectedly shares the live upstream DNS alias")
        self.wait_web(self.record["candidates"], self.revision)
        self.save("candidates-verified")

    def addresses(self, identifiers: dict[str, str]) -> dict[str, str]:
        nginx_networks = self.container("nginx")["NetworkSettings"]["Networks"]
        result = {}
        for name, identifier in identifiers.items():
            networks = self.inspect(identifier)["NetworkSettings"]["Networks"]
            common = [entry["IPAddress"] for key, entry in networks.items() if key in nginx_networks and entry["NetworkID"] == nginx_networks[key]["NetworkID"]]
            if len(common) != 1:
                raise ReleaseError("Expected one verified shared Nginx network")
            result[name] = str(ipaddress.IPv4Address(common[0]))
        return result

    def nginx_write(self, content: str) -> None:
        # A single-file Docker bind retains its inode: replacing the host file
        # atomically would leave Nginx reading stale bytes. Test before reload.
        path = self.root / "nginx/nginx.conf"
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def nginx_workers(self) -> set[str]:
        output = self.run("docker", "top", self.container("nginx")["Id"], "-eo", "pid,args")
        return set(re.findall(r"^\s*(\d+)\s+nginx: worker process", output, re.M))

    def drain_upstreams(self, identifiers: dict[str, str]) -> None:
        """Wait only for generations referencing the pair about to be stopped.

        A failed first switch can route back to the still-running old pair and
        retire only candidate generations. Long-lived original connections do
        not block that recovery or require their workers to be terminated.
        """
        target = set(identifiers.values())
        for attempt in range(60):
            live = self.nginx_workers()
            pending = {pid for pid, references in self.record["nginx_bindings"].items()
                       if pid in live and target.intersection(references)}
            if not pending:
                return
            if attempt == 59:
                raise ReleaseError("Prior Nginx requests have not drained; retaining both serving web pairs")
            time.sleep(2)

    def route(self, identifiers: dict[str, str] | None) -> None:
        self.verify_binding()
        targets = identifiers or {name: self.container(name)["Id"] for name in WEB}
        before = self.nginx_workers()
        if not before:
            raise ReleaseError("Nginx has no identifiable serving workers")
        prior_targets = self.record.get("pending_route", {}).get("targets", self.record["serving"])
        for pid in before:
            self.record["nginx_bindings"].setdefault(pid, list(prior_targets.values()))
        current = (self.root / "nginx/nginx.conf").read_text()
        original = self.original_nginx.read_text()
        wanted = web_configuration(original, self.addresses(identifiers)) if identifiers else original
        self.record["pending_route"] = {"targets": targets, "previous_workers": sorted(before)}
        self.save(self.record["phase"])
        self.nginx_write(wanted)
        try:
            self.run("docker", "exec", self.container("nginx")["Id"], "nginx", "-t")
            self.run("docker", "exec", self.container("nginx")["Id"], "nginx", "-s", "reload")
            for attempt in range(30):
                added = self.nginx_workers() - before
                if added:
                    for pid in added:
                        self.record["nginx_bindings"][pid] = list(targets.values())
                    self.record["serving"] = targets
                    self.record.pop("pending_route", None)
                    self.save(self.record["phase"])
                    return
                if attempt == 29:
                    raise ReleaseError("Nginx did not establish a replacement worker generation")
                time.sleep(1)
        except BaseException:
            self.nginx_write(current)
            self.run("docker", "exec", self.container("nginx")["Id"], "nginx", "-t")
            self.run("docker", "exec", self.container("nginx")["Id"], "nginx", "-s", "reload")
            raise

    def public_probe(self, revision: str, *, full: bool = False) -> None:
        for attempt in range(15):
            try:
                payload = self.run("curl", "--silent", "--show-error", "--max-time", "20", "https://tech.gctravels.com/api/v1/health/ready")
                validate_readiness(json.loads(payload), revision, full=full)
                break
            except (ReleaseError, ValueError):
                if attempt == 14:
                    raise
                time.sleep(2)
        for route in ("/login", "/assets/upload-samples/visa-photo.png"):
            status = self.run("curl", "--silent", "--show-error", "--max-time", "20", "--output", "/dev/null", "--write-out", "%{http_code}", "https://tech.gctravels.com" + route)
            if status != "200":
                raise ReleaseError("Public login or existing sample asset did not return HTTP 200")

    def stop_candidates(self) -> None:
        for identifier in self.record["candidates"].values():
            ids = self.run("docker", "ps", "-aq", "--filter", f"name=^/{identifier}$").split()
            if ids:
                self.run("docker", "stop", "--time", "60", ids[0], timeout=90)

    def update_originals(self, services: tuple[str, ...], *, previous: bool = False) -> None:
        self.verify_binding()
        old_pin = self.pin_path
        old_revision = self.env["APP_REVISION"]
        try:
            if previous:
                self.pin_path = self.recovery_pin
                self.env["APP_REVISION"] = self.record["previous_revision"]
            self.dc("up", "-d", "--no-deps", "--no-build", "--pull", "never", "--timeout", "60", *services, pinned=True, timeout=600)
        finally:
            self.pin_path = old_pin
            self.env["APP_REVISION"] = old_revision

    def transition(self, config: dict) -> None:
        """Keep candidates serving until replacement web containers are proved."""
        self.require_current_main()
        self.pause_workers()
        self.start_candidates(config)
        self.unchanged_infrastructure()
        self.route(self.record["candidates"])
        self.save("candidate-routing")
        self.public_probe(self.revision)
        self.drain_upstreams({name: self.record["original"][name]["id"] for name in WEB})
        self.record["original_recreated"] = True
        self.save("replacing-original-web")
        self.update_originals(WEB)
        originals = {name: self.container(name)["Id"] for name in WEB}
        self.wait_web(originals, self.revision)
        self.route(originals)
        self.save("new-web-routing")
        self.public_probe(self.revision)
        self.drain_upstreams(self.record["candidates"])
        self.stop_candidates()
        self.save("restarting-workers")
        self.update_originals(self.workers)
        self.wait_workers()
        self.wait_web(originals, self.revision, full=True)
        self.public_probe(self.revision, full=True)
        self.verify_containers(self.activated_services, self.record["images"])
        self.unchanged_infrastructure()
        self.route(None)
        self.public_probe(self.revision, full=True)
        self.write_private(self.root / ".env", updated_environment(self.original_env.read_text(), self.revision, self.expected_schema))
        self.record["final_overlay"] = str(self.pin_path)
        self.save("complete")

    def require_current_main(self) -> None:
        self.run("git", "fetch", "origin", "main", timeout=180)
        if self.run("git", "rev-parse", "origin/main") != self.revision:
            raise ReleaseError("A newer main revision arrived before production transition")

    def wait_workers(self) -> None:
        for attempt in range(30):
            try:
                self.worker_probe(idle=False)
                return
            except ReleaseError:
                if attempt == 29:
                    raise
                time.sleep(2)

    def restore_consumers(self) -> None:
        # A drain failure may leave live workers with some consumers cancelled.
        # Restore their reviewed queues without restarting active tasks.
        queues = {name: WORKER_COMMANDS[name][1].split(",") for name in self.node_prefixes}
        nodes = {f"{prefix}@{self.container(name)['Config']['Hostname']}": queues[name]
                 for name, prefix in self.node_prefixes.items()}
        self.worker_control("""
import json,sys
from app.infrastructure.processing.celery_app import celery_app
for node,queues in json.loads(sys.argv[1]).items():
 for queue in queues:
  replies=celery_app.control.add_consumer(queue,destination=[node],reply=True,timeout=10)
  assert replies and any(node in value and 'ok' in value[node] for value in replies), 'Consumer restore not acknowledged'
""", json.dumps(nodes))

    def recover(self) -> None:
        """Recover app images only; never change or restore persistent data."""
        self.save("recovering")
        self.verify_binding()
        self.unchanged_infrastructure()
        # Before original replacement, the old serving pair is still intact.
        # Afterwards, a verified candidate carries ingress during restoration.
        if self.record.get("original_recreated"):
            candidates = self.record["candidates"]
            running = all(self.inspect(identifier)["State"].get("Running") for identifier in candidates.values())
            # On a late failure, workers may have restarted and staging web may
            # be stopped. Drain again before admitting the extra web memory.
            self.pause_workers()
            if not running:
                config = json.loads(self.dc("config", "--format", "json"))
                self.live_capacity(config, workers_paused=True)
                self.run("docker", "start", *candidates.values(), timeout=120)
            if len(candidates) != 2:
                raise ReleaseError("Recovery needs both verified candidate web containers")
            self.wait_web(candidates, self.revision)
            self.route(candidates)
            # Compose can fail after removing/stopping only one old service.
            # Its absence is not a reason to abandon the verified serving pair.
            prior = {name: self.record["original"][name]["id"] for name in WEB}
            prior.update({"current-" + name: item["Id"] for name in WEB
                          if (item := self.optional_existing(name)) is not None})
            self.drain_upstreams(prior)
            self.update_originals(WEB, previous=True)
        originals = {name: self.container(name)["Id"] for name in WEB}
        self.wait_web(originals, self.record["previous_revision"])
        self.route(originals)
        self.drain_upstreams(self.record["candidates"])
        self.stop_candidates()
        # A restart also reattaches queues after partial consumer cancellation.
        # No task is submitted, purged or acknowledged by this release helper.
        if self.record.get("original_recreated"):
            self.update_originals(self.workers, previous=True)
        else:
            for name in self.workers:
                item = self.existing(name)
                if item["Id"] != self.record["original"][name]["id"] or item["Image"] != self.record["original"][name]["image"]:
                    raise ReleaseError("An original worker changed during the drain")
                if not item["State"].get("Running"):
                    self.run("docker", "start", item["Id"], timeout=90)
        self.wait_workers()
        self.restore_consumers()
        self.wait_web(originals, self.record["previous_revision"], full=True)
        self.route(None)
        self.public_probe(self.record["previous_revision"], full=True)
        self.write_private(self.root / ".env", self.original_env.read_text())
        self.unchanged_infrastructure()
        self.save("recovered")

    def run_update(self) -> None:
        if self.receipt_path.exists():
            self.record = json.loads(self.receipt_path.read_text())
            if self.record.get("root") != str(self.root) or self.record.get("revision") != self.revision:
                raise ReleaseError("Existing recovery receipt identity is invalid")
            if self.record.get("phase") == "complete":
                self.compose = self.record["compose"]
                self.public_probe(self.revision, full=True)
                self.unchanged_infrastructure()
                self.say("Previously completed qualified code update verified")
                return
            if self.record.get("phase") != "recovered":
                self.compose = self.record["compose"]
                for filename, expected in self.record["compose_sha256"].items():
                    if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != expected:
                        raise ReleaseError("Recovery Compose file changed since preparation")
                for path, key in ((self.original_env, "original_env_sha256"), (self.original_nginx, "original_nginx_sha256")):
                    if hashlib.sha256(path.read_bytes()).hexdigest() != self.record[key]:
                        raise ReleaseError("Protected recovery backup changed")
                self.recover()
                raise ReleaseError("Interrupted update recovered; rerun for a fresh backed-up attempt")
        config = self.prepare()
        try:
            self.transition(config)
        except BaseException:
            try:
                self.recover()
            except BaseException as recovery_error:
                self.save("recovery-required")
                raise ReleaseError(f"Update stopped; app recovery needs attention. Protected receipt: {self.receipt_path}") from recovery_error
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    def interrupted(signum: int, frame: Any) -> None:
        raise ReleaseError("Release interrupted; initiating recorded same-schema recovery")
    signal.signal(signal.SIGTERM, interrupted)
    release = CodeUpdate(args.revision, args.root, args.manifest)
    try:
        with release_lock(release.lock_directory):
            release.run_update()
    except (ReleaseError, ValueError, OSError, KeyboardInterrupt) as error:
        print(f"Code update stopped: {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
