"""Run the two existing returning-contact races against disposable PostgreSQL.

Only test sources and five hash-locked pytest packages are mounted. Application
code and production dependencies always come from the immutable candidate image.
The caller preregisters both container names and owns their labelled cleanup.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    from .bounded_qualification_output import capture
    from .qualify_postgresql_client import (
        OWNER_LABEL,
        QualificationError,
        inspect_image,
        run,
    )
except ImportError:
    from bounded_qualification_output import capture
    from qualify_postgresql_client import (
        OWNER_LABEL,
        QualificationError,
        inspect_image,
        run,
    )

PACKAGES = frozenset({"pytest", "pytest-asyncio", "iniconfig", "pluggy", "pygments"})
TEST_FILE = "tests/service_integration/test_returning_reuse_postgresql.py"
TEST_NAMES = frozenset({
    "test_parallel_contact_retries_create_one_binding_without_deadlock",
    "test_contact_recovery_and_old_grant_reads_share_lock_order",
})
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def extract_test_sources(source_root: Path, source_commit: str, target: Path) -> str:
    """Read an exact Git snapshot; O(source bytes) with a fixed 64 MiB ceiling."""
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise QualificationError("Contact tests require an exact source revision")
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "archive", "--format=tar", source_commit,
             "backend/tests", "backend/pyproject.toml", "backend/requirements-dev.lock"],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise QualificationError("Could not capture the candidate test sources") from None
    if result.returncode or len(result.stdout) > MAX_SOURCE_BYTES:
        raise QualificationError("Candidate test archive is unavailable or oversized")
    target.mkdir(mode=0o755)
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive:
            parts = Path(member.name).parts
            allowed = (member.name in {"backend", "backend/tests", "backend/pyproject.toml",
                                      "backend/requirements-dev.lock"}
                       or member.name.startswith("backend/tests/"))
            if (not allowed or ".." in parts or Path(member.name).is_absolute()
                    or member.name in seen or len(seen) >= 4000
                    or not (member.isdir() or member.isfile())):
                raise QualificationError("Candidate test archive contains an unexpected entry")
            seen.add(member.name)
            destination = target.joinpath(*parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o755)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise QualificationError("Candidate test archive has an unreadable entry")
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            destination.write_bytes(source.read())
            destination.chmod(0o644)
    if not {f"backend/{TEST_FILE}", "backend/pyproject.toml", "backend/requirements-dev.lock"} <= seen:
        raise QualificationError("Candidate test source closure is incomplete")
    return hashlib.sha256(result.stdout).hexdigest()


def minimal_requirements(lock: str) -> tuple[str, dict[str, tuple[str, set[str]]]]:
    """Select reviewed lock entries; never resolve or install runtime packages."""
    entries: dict[str, tuple[str, set[str]]] = {}
    blocks: list[str] = []
    for block in re.split(r"(?m)(?=^[a-zA-Z0-9][^\n]*==)", lock):
        match = re.match(r"([a-z][a-z0-9-]*)==([0-9][0-9.]*)\s*\\", block)
        if match is None or match[1] not in PACKAGES:
            continue
        hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", block))
        if not hashes or match[1] in entries:
            raise QualificationError("The test dependency lock is incomplete or ambiguous")
        entries[match[1]] = (match[2], hashes)
        continuation = " " + chr(92) + "\n"
        blocks.append(continuation.join([f"{match[1]}=={match[2]}",
                                        *(f"    --hash=sha256:{digest}" for digest in sorted(hashes))]))
    if entries.keys() != PACKAGES:
        raise QualificationError("The five reviewed test dependencies must be hash locked")
    return "\n".join(blocks) + "\n", entries


def _download(url: str, *, maximum: int, host: str) -> bytes:
    """Public package bytes only; no credentials and bounded transfer/time."""
    from urllib.parse import urlsplit

    def allowed(value: str) -> bool:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and parsed.netloc == host

    if not allowed(url):
        raise QualificationError("Unapproved test package download location")
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            if not allowed(response.geturl()):
                raise QualificationError("Unapproved test package redirect")
            content: bytes = response.read(maximum + 1)
    except (OSError, TimeoutError):
        raise QualificationError("Could not download a reviewed test dependency") from None
    if len(content) > maximum:
        raise QualificationError("A test dependency exceeds its size boundary")
    return content


def prepare_wheelhouse(entries: dict[str, tuple[str, set[str]]], directory: Path) -> dict[str, str]:
    directory.mkdir(mode=0o755)
    receipts: dict[str, str] = {}
    for name, (version, allowed_hashes) in sorted(entries.items()):
        metadata = json.loads(_download(f"https://pypi.org/pypi/{name}/{version}/json",
                                        maximum=2 * 1024 * 1024, host="pypi.org"))
        filename = f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
        candidates = [item for item in metadata["urls"] if item.get("filename") == filename]
        if len(candidates) != 1 or candidates[0].get("digests", {}).get("sha256") not in allowed_hashes:
            raise QualificationError("The exact pure-Python test wheel is absent from the reviewed lock")
        content = _download(candidates[0]["url"], maximum=16 * 1024 * 1024, host="files.pythonhosted.org")
        digest = hashlib.sha256(content).hexdigest()
        if digest not in allowed_hashes or digest != candidates[0]["digests"]["sha256"]:
            raise QualificationError("A test wheel failed its reviewed SHA-256 check")
        path = directory / filename
        path.write_bytes(content)
        path.chmod(0o644)
        receipts[filename] = digest
    return receipts


def validate_junit(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise QualificationError("Contact test evidence is absent or oversized")
    try:
        raw = path.read_bytes()
        root = ET.fromstring(raw)
        suites = list(root.iter("testsuite"))
        cases = list(root.iter("testcase"))
        expected_class = "tests.service_integration.test_returning_reuse_postgresql"
        if (len(suites) != 1 or len(cases) != 2
                or {case.get("name") for case in cases} != TEST_NAMES
                or any(case.get("classname") != expected_class or len(case) for case in cases)
                or any(suites[0].get(key) != value for key, value in
                       {"tests": "2", "failures": "0", "errors": "0", "skipped": "0"}.items())):
            raise QualificationError("Both exact PostgreSQL contact tests must pass without skips")
    except (ET.ParseError, OSError):
        raise QualificationError("Contact test evidence is unreadable") from None
    return {"contact_concurrency_tests": 2, "contact_concurrency_verified": True,
            "junit_sha256": hashlib.sha256(raw).hexdigest()}


def _container(name: str, owner: str) -> list[str]:
    return ["docker", "create", "--name", name, "--label", f"{OWNER_LABEL}={owner}",
            "--log-driver", "json-file", "--log-opt", "max-size=1m", "--log-opt", "max-file=2",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "128",
            "--user", f"{os.getuid()}:{os.getgid()}", "--tmpfs", "/tmp:rw,nosuid,size=128m",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONNOUSERSITE=1"]


def validate_diagnostic_path(path: Path | None) -> None:
    if path is None:
        return
    parent = path.absolute().parent
    if (path.name != "fast-contact-check.private.log" or parent.resolve(strict=True) != parent
            or not parent.is_dir() or path.exists() or path.is_symlink()
            or (os.name == "posix" and parent.stat().st_mode & 0o077)):
        raise QualificationError("Contact diagnostics require a new log in a private regular directory")


def run_contact_tests(*, image: str, server_id: str, owner: str, tempdir: Path,
                      env_file: Path, container_name: str, dependency_container_name: str,
                      source_root: Path, source_commit: str,
                      diagnostic_path: Path | None = None) -> dict[str, Any]:
    """Caller owns all resource cleanup, including failures during create/start."""
    validate_diagnostic_path(diagnostic_path)
    if os.name != "posix" or re.fullmatch(r"[0-9a-f]{64}", server_id) is None:
        raise QualificationError("Contact qualification requires an immutable isolated Linux server")
    image_id = inspect_image(image, source_commit)
    image_details = json.loads(run(["docker", "image", "inspect", image_id]).stdout)[0]
    image_environment = dict(item.split("=", 1) for item in image_details["Config"].get("Env", []))
    # Fast candidates intentionally precede inherited site-packages with their
    # production MCP compatibility overlay. Preserve that exact precedence.
    pythonpath = "/qa-overlay:" + image_environment.get("PYTHONPATH", "/app")
    server = json.loads(run(["docker", "container", "inspect", server_id]).stdout)[0]
    if (server.get("Config", {}).get("Labels", {}) or {}).get(OWNER_LABEL) != owner:
        raise QualificationError("Contact qualification refused an unrelated PostgreSQL server")
    archive_sha = extract_test_sources(source_root, source_commit, tempdir / "contact-source")
    source = tempdir / "contact-source" / "backend"
    lock, entries = minimal_requirements((source / "requirements-dev.lock").read_text(encoding="utf-8"))
    lockfile = tempdir / "contact-requirements.lock"
    lockfile.write_text(lock, encoding="utf-8")
    wheelhouse = tempdir / "contact-wheels"
    wheels = prepare_wheelhouse(entries, wheelhouse)
    overlay = tempdir / "contact-overlay"
    output = tempdir / "contact-results"
    overlay.mkdir(mode=0o755)
    output.mkdir(mode=0o755)
    run([*_container(dependency_container_name, owner), "--network", "none",
         "--mount", f"type=bind,source={lockfile},target=/qa-requirements.lock,readonly",
         "--mount", f"type=bind,source={wheelhouse},target=/qa-wheels,readonly",
         "--mount", f"type=bind,source={overlay},target=/qa-overlay",
         "--entrypoint", "python", image_id, "-m", "pip", "--isolated", "install", "--no-index",
         "--find-links=/qa-wheels", "--only-binary=:all:", "--no-deps", "--require-hashes",
         "--no-cache-dir", "--no-compile", "--target=/qa-overlay", "-r", "/qa-requirements.lock"])
    run(["docker", "start", "--attach", dependency_container_name], timeout=90)
    environment = dict(line.split("=", 1) for line in env_file.read_text().splitlines()
                       if line and not line.startswith("#"))
    database = "passdetection_ci_returning_" + hashlib.sha256(owner.encode()).hexdigest()[:12]
    # Do not carry the rehearsal's library paths, feature flags or other settings
    # into this image. The only shared values are its synthetic DB credentials.
    contact_env = tempdir / "contact.env"
    descriptor = os.open(contact_env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("\n".join(f"{key}={environment[key]}" for key in
                               ("POSTGRES_USER", "POSTGRES_PASSWORD")) + "\n")
    run(["docker", "exec", server_id, "createdb", "-U", environment["POSTGRES_USER"], database])
    run([*_container(container_name, owner), "--network", f"container:{server_id}", "--workdir", "/app",
         "--env-file", str(contact_env), "--env", "POSTGRES_HOST=127.0.0.1", "--env", "POSTGRES_PORT=5432",
         "--env", "POSTGRES_DB=passdetection_ci_unbound_contact_application",
         "--env", f"FCM_TEST_POSTGRES_DB={database}", "--env", "FCM_TEST_KEEP_SCHEMA=0",
         "--env", "RUN_SERVICE_INTEGRATION=1", "--env", "APP_ENV=development",
         "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", "--env", f"PYTHONPATH={pythonpath}",
         "--env", "OPENBLAS_NUM_THREADS=1", "--env", "OMP_NUM_THREADS=1",
         "--mount", f"type=bind,source={source / 'tests'},target=/app/tests,readonly",
         "--mount", f"type=bind,source={source / 'pyproject.toml'},target=/app/pyproject.toml,readonly",
         "--mount", f"type=bind,source={overlay},target=/qa-overlay,readonly",
         "--mount", f"type=bind,source={output},target=/qa-results",
         "--entrypoint", "python", image_id, "-m", "pytest", "-p", "pytest_asyncio.plugin",
         "-o", "addopts=", "-o", "cache_dir=/tmp/pytest-cache", "--basetemp=/tmp/pytest-contact",
         "--junitxml=/qa-results/contact.xml", "-q", TEST_FILE])
    capture(["docker", "start", "--attach", container_name], timeout=180,
            diagnostic_path=diagnostic_path)
    return {**validate_junit(output / "contact.xml"), "test_source_commit": source_commit,
            "test_source_archive_sha256": archive_sha,
            "test_dependency_lock_sha256": hashlib.sha256(lock.encode()).hexdigest(),
            "test_wheels": wheels, "candidate_image_id": image_id}
