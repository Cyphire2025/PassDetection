"""Restricted SSH entrypoint for a signed, same-schema production release.

Install this file outside the checkout, owned by root, and bind the CI public
key to ``python3 /opt/globalconnect-release-tools/release_ci_dispatch.py`` with
OpenSSH's ``restrict,command=`` options. The key accepts only a full main SHA.
The actual release runs in a systemd unit so an interrupted CI connection does
not terminate an in-flight recovery. Logs and source checkouts are retained.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

REPOSITORY = "Cyphire2025/PassDetection"
ROOT = Path("/opt/GlobalConnectsDashboard")
TOOLS = Path("/opt/globalconnect-release-tools")
GH = TOOLS / "gh-2.92.0/gh"
REVISION = re.compile(r"[0-9a-f]{40}")
REQUIRED_JOBS = frozenset({
    "Required CI checks",
    "Backend — Lint & Compile Check", "Backend — Dependency Audit", "Backend — Tests",
    "Backend - PostgreSQL, Redis, Private S3 & Celery",
    "Backend - Populated PostgreSQL Restore & Upgrade", "Frontend — Lint & Type Check",
    "Frontend - Browser Journeys", "Docker — Build Verification",
    "MCP Connector — Windows Tests & Wheel",
    "Promote qualified image digests and signed inventory",
})


def requested_revision(command: str) -> str:
    prefix = "deploy-qualified:"
    if not command.startswith(prefix) or not REVISION.fullmatch(command[len(prefix):]):
        raise ValueError("This key accepts only deploy-qualified:<full main commit SHA>")
    return command[len(prefix):]


def qualified_run(runs: list[dict], revision: str, jobs_for_run) -> int:
    """Require every actual qualification/promotion gate, not just a workflow name."""
    for run in runs:
        if (run.get("head_sha") != revision or run.get("head_branch") != "main"
                or run.get("event") not in {"push", "workflow_dispatch"} or run.get("path") != ".github/workflows/ci.yml"
                or run.get("repository", {}).get("full_name") != REPOSITORY):
            continue
        jobs = jobs_for_run(run["id"])
        by_name = {job["name"]: job for job in jobs}
        if all(by_name.get(name, {}).get("conclusion") == "success" for name in REQUIRED_JOBS):
            return int(run["id"])
    raise ValueError("No exact-main CI run has passed every qualification and signed-promotion gate")


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, encoding="utf-8").strip()


def api(path: str):
    return json.loads(run(str(GH), "api", path))


@contextlib.contextmanager
def dispatch_lock():
    # Held by the detached systemd child through final runtime verification.
    # Actions concurrency alone cannot serialize a surviving disconnected run.
    import fcntl

    directory = ROOT / "tmp/compose-release-lock"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (directory / "ci-dispatch.lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another CI deployment is still running on the VPS") from error
        yield


def require_current_main(revision: str) -> None:
    run("git", "fetch", "origin", "main", cwd=ROOT)
    if run("git", "rev-parse", "refs/remotes/origin/main", cwd=ROOT) != revision:
        raise ValueError("Refusing a superseded release: requested revision is not current main")


def deploy(revision: str, *, mode: str = "full") -> None:
    if not REVISION.fullmatch(revision):
        raise ValueError("Full revision required")
    if mode not in {"full", "fast"}:
        raise ValueError("Explicit full or fast mode required")
    os.umask(0o022)
    # Fetch objects only. The running checkout and its bind-mounted configuration
    # stay intact until the release helper reports successful activation.
    require_current_main(revision)
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=ROOT):
        raise ValueError("Production checkout has tracked changes; preserve them for review")
    ci_run = None
    if mode == "full":
        runs = api(f"repos/{REPOSITORY}/actions/runs?head_sha={revision}&per_page=100")["workflow_runs"]
        ci_run = qualified_run(runs, revision, lambda identifier: api(
            f"repos/{REPOSITORY}/actions/runs/{identifier}/jobs?per_page=100")["jobs"])
    work = ROOT / "tmp" / f"mcp-direct-{revision}-{uuid.uuid4().hex}"
    work.mkdir(parents=True, mode=0o700)
    work.chmod(0o700)
    source = work / "source"
    run("git", "clone", "--shared", "--no-checkout", str(ROOT), str(source))
    run("git", "checkout", "--detach", revision, cwd=source)
    artifacts = work / "artifacts"
    artifacts.mkdir(mode=0o700)
    if mode == "full":
        run(str(GH), "release", "download", f"release-{revision}", "--repo", REPOSITORY,
            "--pattern", "release-artifacts.json", "--dir", str(artifacts))
    os.environ["PATH"] = str(GH.parent) + os.pathsep + os.environ.get("PATH", "")
    require_current_main(revision)
    print(f"Preparing {mode} revision {revision}; qualified CI run={ci_run}", flush=True)
    command = [sys.executable, "-B", str(source / "scripts/release_retained_update.py"),
               "--revision", revision, "--mode", mode]
    if mode == "full":
        command.extend(["--manifest", str(artifacts / "release-artifacts.json")])
    subprocess.run(command, cwd=source, check=True)
    # Guard the unchanged historical infrastructure source after activation.
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=ROOT):
        raise ValueError("Release is live, but historical infrastructure source changed during deployment")
    # ROOT contains live bind-mounted infrastructure configuration from its
    # historical checkout. Advancing it here would mutate those mounted files.
    # The exact deployed source is retained beside the immutable receipts.
    print(f"DEPLOYMENT COMPLETE mode={mode} revision={revision} run={ci_run} source={source}", flush=True)


def serve(command: str, *, operator_fast: bool = False) -> int:
    revision = requested_revision(command)
    logs = TOOLS / "deployment-logs"
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    logs.chmod(0o700)
    identifier = f"passdetection-deploy-{revision[:12]}-{uuid.uuid4().hex[:8]}"
    log = logs / f"{identifier}.log"
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    print(f"Starting retained deployment unit {identifier}", flush=True)
    result = subprocess.run([
        "systemd-run", "--quiet", "--wait", "--collect", f"--unit={identifier}",
        "--property=Type=exec", "--property=User=root", "--property=SetLoginEnvironment=yes",
        "--property=WorkingDirectory=/root", "--property=UMask=0077",
        "--setenv=GH_CONFIG_DIR=/root/.config/gh", "--setenv=DOCKER_CONFIG=/root/.docker",
        f"--property=StandardOutput=append:{log}", f"--property=StandardError=append:{log}",
        sys.executable, "-B", str(Path(__file__).resolve()), "--run-fast" if operator_fast else "--run", revision,
    ])
    # Detailed logs may contain third-party diagnostics. Keep them on the VPS;
    # only the bounded outcome is returned to the Actions log.
    print(f"Deployment {'completed' if result.returncode == 0 else 'failed'}; retained log {log}", flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run")
    parser.add_argument("--run-fast")
    parser.add_argument("--operator-fast")
    args = parser.parse_args()
    try:
        if sum(value is not None for value in (args.run, args.run_fast, args.operator_fast)) > 1:
            raise ValueError("Select exactly one dispatch operation")
        if args.operator_fast:
            # Not reachable through the forced CI SSH command: only a separate
            # administrator session may choose the lower-assurance build path.
            if os.environ.get("SSH_ORIGINAL_COMMAND") or getattr(os, "geteuid", lambda: -1)() != 0:
                raise ValueError("Fast deployment requires a separate root operator session")
            return serve("deploy-qualified:" + args.operator_fast, operator_fast=True)
        if args.run or args.run_fast:
            if args.run_fast and (os.environ.get("SSH_ORIGINAL_COMMAND") or getattr(os, "geteuid", lambda: -1)() != 0):
                raise ValueError("Fast deployment requires a separate root operator session")
            with dispatch_lock():
                deploy(args.run or args.run_fast, mode="fast" if args.run_fast else "full")
            return 0
        return serve(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"DEPLOYMENT REFUSED: {type(error).__name__}; inspect retained private logs", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
