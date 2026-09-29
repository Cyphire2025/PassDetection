"""Build retained direct-release candidates from exact existing runtime images.

This operator-only module never changes a running container or removes anything.
The caller must drain enough workers before admitting a bounded builder. Original
runtime images and every new builder remain available for inspection/recovery.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

GIB = 1024**3
IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
REVISION = re.compile(r"[a-f0-9]{40}")
NODE_IMAGE = "sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1"


class BuildError(ValueError):
    pass


def contract_digest(source: bytes) -> str:
    """Compare canonical OpenAPI JSON, independent of checkout line endings."""
    canonical = json.dumps(json.loads(source), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return hashlib.sha256(canonical.encode()).hexdigest()


def command(*args: str, timeout: int = 60) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise BuildError("direct_build_command_failed")
    return (result.stdout + (result.stderr if args[:2] == ("docker", "logs") else "")).strip()


def dependency_delta(previous: str, current: str) -> str:
    """Preserve hash/marker blocks and prohibit removing an installed requirement."""
    def packages(content: str) -> dict[str, str]:
        blocks = re.split(r"(?=^[a-zA-Z0-9_.-]+==)", content, flags=re.M)[1:]
        result = {}
        for block in blocks:
            name = block.split("==", 1)[0]
            if name in result or not re.search(r"--hash=sha256:[a-f0-9]{64}", block):
                raise BuildError("invalid_dependency_lock")
            result[name] = block
        if not result:
            raise BuildError("empty_dependency_lock")
        return result
    before, after = packages(previous), packages(current)
    if set(before) - set(after):
        raise BuildError("dependency_removal_requires_separate_review")
    def identity(block: str) -> str:
        return block.splitlines()[0]
    changed = [block for name, block in after.items()
               if name not in before or identity(block) != identity(before[name])]
    return "# Exact source-lock additions/upgrades for an immutable retained base.\n" + "".join(changed)


def admit_builder(running: list[dict], host_bytes: int, builder_bytes: int) -> None:
    if not 0 < builder_bytes <= 3 * GIB:
        raise BuildError("invalid_builder_budget")
    caps = [item.get("HostConfig", {}).get("Memory") for item in running]
    if any(type(value) is not int or value <= 0 for value in caps):
        raise BuildError("unbounded_running_container")
    if sum(caps) + builder_bytes + 2 * GIB > host_bytes:
        raise BuildError("builder_exceeds_host_reserve")


class RetainedBuild:
    def __init__(self, source: Path, output: Path, revision: str,
                 *, run: Callable[..., str] = command):
        if not REVISION.fullmatch(revision) or source.resolve() != source or not source.is_dir():
            raise BuildError("invalid_build_source")
        if output.resolve() != output or not output.is_dir() or output.is_symlink():
            raise BuildError("invalid_build_output")
        self.source, self.output, self.revision, self.run = source, output, revision, run

    def capacity(self, maximum: int) -> None:
        identifiers = self.run("docker", "ps", "-q", "--no-trunc").split()
        running = json.loads(self.run("docker", "inspect", *identifiers)) if identifiers else []
        host_bytes = int(self.run("docker", "info", "--format", "{{.MemTotal}}"))
        admit_builder(running, host_bytes, maximum)

    def existing(self, name: str) -> bool:
        names = self.run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines()
        return name in names

    def create(self, family: str, image: str, maximum: int, entrypoint: str,
               arguments: list[str], environment: dict[str, str]) -> str:
        name = f"mcp-build-{self.revision[:12]}-{family}"
        if self.existing(name):
            raise BuildError("retained_builder_exists_inspect_before_retry")
        self.capacity(maximum)
        args = ["docker", "create", "--name", name, "--memory", str(maximum),
                "--memory-swap", str(maximum), "--cpus", "2", "--pids-limit", "256",
                "--security-opt", "no-new-privileges", "--cap-drop", "ALL", "--user", "0:0",
                "--workdir", "/app", "--entrypoint", entrypoint,
                "--label", f"globalconnects.direct_revision={self.revision}"]
        for key, value in sorted(environment.items()):
            args.extend(["--env", f"{key}={value}"])
        identifier = self.run(*args, image, *arguments)
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise BuildError("invalid_builder_identity")
        return identifier

    def execute(self, identifier: str, family: str, maximum: int) -> dict:
        self.capacity(maximum)
        self.run("docker", "start", identifier)
        print(json.dumps({"phase": "building", "family": family, "container_id": identifier}), flush=True)
        try:
            code = self.run("docker", "wait", identifier, timeout=1800)
        except subprocess.TimeoutExpired:
            # Never terminate or remove a timed-out build; its identity is retained.
            raise BuildError("builder_still_running_inspect_before_retry") from None
        state = json.loads(self.run("docker", "inspect", "--format", "{{json .State}}", identifier))
        log_path = self.output / f"{family}-build.log"
        with log_path.open("x", encoding="utf-8") as stream:
            stream.write(self.run("docker", "logs", identifier, timeout=60))
        if code != "0" or state.get("Running") or state.get("OOMKilled"):
            raise BuildError("builder_failed_retained_log_available")
        return {"container_id": identifier, "exit_code": 0, "oom_killed": False,
                "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest()}

    def backend(self, base_image: str, previous_lock: Path) -> dict:
        if not IMAGE.fullmatch(base_image):
            raise BuildError("immutable_backend_base_required")
        lock = self.output / "backend-delta.lock"
        with lock.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(dependency_delta(previous_lock.read_text(),
                                         (self.source / "backend/requirements.lock").read_text()))
        contract_sha = contract_digest((self.source / "backend/contracts/api.openapi.json").read_bytes())
        verification = (
            "import hashlib,json,mcp,pydantic; "
            "from scripts.export_api_contract import application_contract; "
            "assert mcp.__file__.startswith('/opt/mcp-deps/'); "
            "assert pydantic.__file__.startswith('/opt/mcp-deps/'); "
            "raw=(json.dumps(application_contract(),ensure_ascii=False,sort_keys=True,indent=2)+'\\n').encode(); "
            f"assert hashlib.sha256(raw).hexdigest()=={contract_sha!r}; "
            "print('MCP_BUILD_CONTRACT_VERIFIED',flush=True)"
        )
        build_code = (
            "import subprocess,sys; "
            "subprocess.run([sys.executable,'-m','pip','install','--no-deps','--require-hashes',"
            "'--only-binary=:all:','--target','/opt/mcp-deps','-r','/app/mcp-delta.lock'],check=True); "
            "subprocess.run(['/opt/venv/bin/python','-m','pip','check'],check=True); "
            f"subprocess.run(['/opt/venv/bin/python','-c',{verification!r}],check=True)"
        )
        identifier = self.create("backend", base_image, GIB, "/usr/local/bin/python",
                                 ["-c", build_code], {"PYTHONPATH": "/opt/mcp-deps:/app"})
        for directory in ("app", "alembic", "scripts"):
            self.run("docker", "cp", str(self.source / "backend" / directory), f"{identifier}:/app/")
        for filename in ("alembic.ini", "gunicorn.conf.py"):
            self.run("docker", "cp", str(self.source / "backend" / filename), f"{identifier}:/app/{filename}")
        self.run("docker", "cp", str(lock), f"{identifier}:/app/mcp-delta.lock")
        result = self.execute(identifier, "backend", GIB)
        image = self.run("docker", "commit", "--change", "USER 1001:1001",
            "--change", 'ENTRYPOINT []', "--change", 'CMD ["gunicorn","--config","gunicorn.conf.py","app.main:app"]',
            "--change", f"ENV APP_REVISION={self.revision}",
            "--change", "ENV EXPECTED_DATABASE_SCHEMA_REVISION=0122_mcp_gc_push",
            "--change", f"LABEL org.opencontainers.image.revision={self.revision}", identifier)
        if not IMAGE.fullmatch(image):
            raise BuildError("invalid_built_image_identity")
        return {**result, "image_id": image, "base_image_id": base_image,
                "verified_api_contract_sha256": contract_sha,
                "dependency_delta_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()}

    def frontend(self, base_image: str, public_origin: str) -> dict:
        if not IMAGE.fullmatch(base_image) or public_origin != "https://tech.gctravels.com":
            raise BuildError("invalid_frontend_build_binding")
        script = (
            "npm install --prefix /opt/mcp-buildtools npm@11.20.0 && "
            "node /opt/mcp-buildtools/node_modules/npm/bin/npm-cli.js ci && "
            "node /opt/mcp-buildtools/node_modules/npm/bin/npm-cli.js run build"
        )
        identifier = self.create("frontend", NODE_IMAGE, 3 * GIB, "/bin/sh", ["-c", script], {
            "NEXT_PUBLIC_APP_URL": public_origin, "NEXT_PUBLIC_DEV_APP_URL": "",
            "NEXT_PUBLIC_API_BASE_URL": "", "API_BASE_URL": "", "NEXT_TELEMETRY_DISABLED": "1",
            "NEXT_PUBLIC_APP_REVISION": self.revision, "NODE_OPTIONS": "--max-old-space-size=2048",
        })
        self.run("docker", "cp", str(self.source / "frontend") + "/.", f"{identifier}:/app/", timeout=180)
        result = self.execute(identifier, "frontend", 3 * GIB)
        # A second stopped container supplies the already-reviewed minimal runtime.
        runtime_name = f"mcp-build-{self.revision[:12]}-frontend-runtime"
        if self.existing(runtime_name):
            raise BuildError("retained_runtime_builder_exists")
        runtime = self.run("docker", "create", "--name", runtime_name, "--memory", str(GIB // 4),
            "--memory-swap", str(GIB // 4), "--cpus", "1", "--pids-limit", "64",
            "--network", "none", "--user", "0:0", "--entrypoint", "/bin/sh",
            "--security-opt", "no-new-privileges", "--cap-drop", "ALL", "--cap-add", "CHOWN",
            base_image, "-c", "chown -R 1001:1001 /app")
        for source, destination, label in (("/app/.next/standalone/.", "/app/", "standalone"),
                                            ("/app/.next/static", "/app/.next/", "static"),
                                            ("/app/public", "/app/", "public")):
            staging = self.output / f"frontend-{label}"
            staging.mkdir(mode=0o700)
            self.run("docker", "cp", f"{identifier}:{source}", str(staging), timeout=180)
            self.run("docker", "cp", str(staging) + "/.", f"{runtime}:{destination}", timeout=180)
        runtime_result = self.execute(runtime, "frontend-runtime", GIB // 4)
        image = self.run("docker", "commit", "--change", "USER 1001:1001",
                        "--change", 'ENTRYPOINT []', "--change", 'CMD ["node","server.js"]',
                        "--change", f"ENV NEXT_PUBLIC_APP_REVISION={self.revision}",
                        "--change", f"LABEL org.opencontainers.image.revision={self.revision}", runtime)
        if not IMAGE.fullmatch(image):
            raise BuildError("invalid_built_image_identity")
        return {**result, "runtime_container_id": runtime, "runtime_preparation": runtime_result,
                "image_id": image, "base_image_id": base_image}
