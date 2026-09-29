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
                or run.get("event") != "push" or run.get("path") != ".github/workflows/ci.yml"
                or run.get("repository", {}).get("full_name") != REPOSITORY):
            continue
        jobs = jobs_for_run(run["id"])
        by_name = {job["name"]: job for job in jobs}
        if all(by_name.get(name, {}).get("conclusion") == "success" for name in REQUIRED_JOBS):
            return int(run["id"])
    raise ValueError("No main-push CI run has passed every qualification and signed-promotion gate")


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, encoding="utf-8").strip()


def api(path: str):
    return json.loads(run(str(GH), "api", path))


@contextlib.contextmanager
def dispatch_lock():
    # Held by the detached systemd child, including the final checkout update.
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


def deploy(revision: str) -> None:
    if not REVISION.fullmatch(revision):
        raise ValueError("Full revision required")
    os.umask(0o022)
    # Fetch objects only. The running checkout and its bind-mounted configuration
    # stay intact until the release helper reports successful activation.
    require_current_main(revision)
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=ROOT):
        raise ValueError("Production checkout has tracked changes; preserve them for review")
    runs = api(f"repos/{REPOSITORY}/actions/runs?head_sha={revision}&per_page=100")["workflow_runs"]
    ci_run = qualified_run(runs, revision, lambda identifier: api(
        f"repos/{REPOSITORY}/actions/runs/{identifier}/jobs?per_page=100")["jobs"])
    work = TOOLS / "qualified-releases" / f"{revision}-{uuid.uuid4().hex}"
    work.mkdir(parents=True, mode=0o700)
    work.chmod(0o700)
    source = work / "source"
    run("git", "clone", "--shared", "--no-checkout", str(ROOT), str(source))
    run("git", "checkout", "--detach", revision, cwd=source)
    artifacts = work / "artifacts"
    artifacts.mkdir(mode=0o700)
    run(str(GH), "release", "download", f"release-{revision}", "--repo", REPOSITORY,
        "--pattern", "release-artifacts.json", "--dir", str(artifacts))
    os.environ["PATH"] = str(GH.parent) + os.pathsep + os.environ.get("PATH", "")
    require_current_main(revision)
    print(f"Verified required CI jobs for run {ci_run}; preparing signed revision {revision}", flush=True)
    subprocess.run([sys.executable, str(source / "scripts/release_code_update.py"),
                    "--revision", revision, "--manifest", str(artifacts / "release-artifacts.json"),
                    "--root", str(ROOT)], cwd=source, check=True)
    # The helper has restored Nginx source and proved the replacement before this
    # checkout advance. Do not overwrite .env, receipts, or retained backups.
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=ROOT):
        raise ValueError("Release is live, but tracked checkout changes prevent source advancement")
    run("git", "merge", "--ff-only", revision, cwd=ROOT)
    print(f"CI DEPLOYMENT COMPLETE revision={revision} run={ci_run}", flush=True)


def serve(command: str) -> int:
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
        sys.executable, str(Path(__file__).resolve()), "--run", revision,
    ])
    # Detailed logs may contain third-party diagnostics. Keep them on the VPS;
    # only the bounded outcome is returned to the Actions log.
    print(f"Deployment {'completed' if result.returncode == 0 else 'failed'}; retained log {log}", flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run")
    args = parser.parse_args()
    try:
        if args.run:
            with dispatch_lock():
                deploy(args.run)
            return 0
        return serve(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"DEPLOYMENT REFUSED: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
