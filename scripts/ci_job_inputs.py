"""Conservative tracked-input fingerprints for routine CI, never release proof.

The caller must independently authenticate a successful GitHub job and its
revision, workflow, PR/base lineage and freshness before considering reuse.
Full/manual qualification must execute every gate again. No mutable worktree,
cache artifact, job output, or user-supplied receipt is an authority here.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path

INPUT_SCHEMA = "passdetection-ci-inputs-v1"
JOBS = (
    "backend-static-checks", "backend-dependency-audit", "backend-test",
    "backend-service-integration", "backend-migration-rehearsal",
    "frontend-lint", "frontend-browser", "connector-windows", "docker-build",
)
ALL_JOBS = frozenset(JOBS)
# Audits have live advisory inputs; static checks include expiry checks. Images
# embed the current revision, so successful old image jobs are not reusable.
REUSABLE_JOBS = frozenset({
    "backend-test", "backend-service-integration", "backend-migration-rehearsal",
    "frontend-browser", "connector-windows",
})
BACKEND_JOBS = frozenset({
    "backend-dependency-audit", "backend-test", "backend-service-integration",
    "backend-migration-rehearsal", "connector-windows", "docker-build",
})
FRONTEND_JOBS = frozenset({"frontend-lint", "frontend-browser", "docker-build"})
STATIC = frozenset({"backend-static-checks"})
BACKEND_FRONTEND_INPUTS = frozenset({
    "frontend/lib/observability/route-templates.json",
    "frontend/features/upload/api/upload.api.ts",
    "frontend/features/passports/api/upload-links.api.ts",
})
FRONTEND_BACKEND_INPUTS = frozenset({
    "backend/app/presentation/api/v1/routes/document_distribution_delivery.py",
    "backend/app/presentation/api/v1/routes/document_distribution_delivery_support.py",
})
FRONTEND_DOC_INPUT = "docs/sources/enterprise-dashboard-ui-transformation-prompt.md"
OBJECT_ID = re.compile(r"[0-9a-f]{40}")
TreeEntry = tuple[str, str, str]  # Git mode, object type, object ID.


def _validate_path(path: str) -> None:
    if (not isinstance(path, str) or not path or "\\" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or any(part in {"", ".", ".."} for part in path.split("/"))):
        raise ValueError("Expected an unambiguous repository-relative Git path")


def _path_jobs(path: str) -> frozenset[str]:
    """Reviewed consumers; any unclassified path invalidates every lane."""
    _validate_path(path)
    if path == FRONTEND_DOC_INPUT:
        return STATIC | {"frontend-lint"}
    # Markdown outside build contexts is read only by repository policy tests.
    # Non-Markdown evidence/policy files are deliberately not exempted.
    if path == "README.md" or (path.startswith("docs/") and path.endswith(".md")):
        return STATIC
    parts = path.split("/")
    if (((len(parts) == 2 and parts[0] == "scripts")
            or (len(parts) == 3 and parts[:2] == ["scripts", "qa"]))
            and parts[-1].startswith("test_") and parts[-1].endswith(".py")):
        return STATIC
    # backend/tests is explicitly excluded by backend/.dockerignore, and no
    # image qualification command imports this suite. Both test lanes remain
    # invalidated: a shared fixture/conftest may affect either one.
    if path.startswith("backend/tests/"):
        return STATIC | {"backend-test", "backend-service-integration"}
    if path.startswith("backend/"):
        result = STATIC | BACKEND_JOBS
        if path.startswith("backend/contracts/"):
            result |= FRONTEND_JOBS
        if path in FRONTEND_BACKEND_INPUTS:
            result |= {"frontend-lint"}
        return result
    if path.startswith("frontend/"):
        # Its Dockerfile copies the complete context. Do not guess that tests,
        # fixtures, configs, or documentation inside this directory are unused.
        result = STATIC | FRONTEND_JOBS
        if path in BACKEND_FRONTEND_INPUTS:
            result |= {"backend-test"}
        return result
    if path.startswith("mcp-connector/"):
        return STATIC | {"connector-windows"}
    if path.startswith("mobile/contracts/"):
        return STATIC | {"backend-test"}
    # Includes CI/planner changes, tooling, QA, infrastructure, root config,
    # mobile source, and new top-level directories. No implicit allow-list.
    return ALL_JOBS


def classify_paths(paths: Iterable[str]) -> frozenset[str]:
    """Return required routine lanes, including stable repository policy checks.

    Pass *both* names for a rename and every addition/deletion. A PR planner
    must use the complete merge-base diff, not just its latest pushed commit.
    Invalid path data raises; the caller must fail closed to all jobs.
    """
    jobs = STATIC
    for path in paths:
        jobs |= _path_jobs(path)
    return jobs


def read_git_tree(repository: Path, revision: str) -> dict[str, TreeEntry]:
    """Read exact committed identities without checkout, shell, or local files."""
    if not isinstance(revision, str) or not OBJECT_ID.fullmatch(revision):
        raise ValueError("A full immutable Git commit SHA is required")
    # A tree/blob SHA must not be mistaken for the source commit that GitHub ran.
    object_type = subprocess.check_output(
        ["git", "-C", str(repository), "cat-file", "-t", revision], timeout=30,
    ).strip()
    if object_type != b"commit":
        raise ValueError("Source revision is not a Git commit")
    raw = subprocess.check_output(
        ["git", "-C", str(repository), "ls-tree", "-r", "-z", "--full-tree", revision],
        timeout=30,
    )
    if not raw or not raw.endswith(b"\0"):
        raise ValueError("Git returned an empty or incomplete tracked tree")
    result: dict[str, TreeEntry] = {}
    for record in raw[:-1].split(b"\0"):
        metadata, path_bytes = record.split(b"\t", 1)
        mode, kind, identifier = metadata.decode("ascii").split(" ")
        path = path_bytes.decode("utf-8")
        _validate_path(path)
        if path in result:
            raise ValueError("Git returned duplicate paths")
        result[path] = (mode, kind, identifier)
    _validate_tree(result)
    return result


def _validate_tree(tree: Mapping[str, TreeEntry]) -> None:
    if not tree or ".github/workflows/ci.yml" not in tree:
        raise ValueError("The complete CI workflow tree is required")
    for path, entry in tree.items():
        _validate_path(path)
        if (not isinstance(entry, tuple) or len(entry) != 3
                or entry[0] not in {"100644", "100755"} or entry[1] != "blob"
                or not isinstance(entry[2], str) or not OBJECT_ID.fullmatch(entry[2])):
            # Symlink targets/submodule contents need dependency expansion. Until
            # implemented, refuse reuse rather than pretend their blobs suffice.
            raise ValueError("Unsupported or malformed tracked object; run all jobs")


def fingerprint_job(job: str, tree: Mapping[str, TreeEntry]) -> str:
    """Hash path, executable mode and blob identity for every reviewed consumer."""
    if job not in ALL_JOBS:
        raise ValueError("Unknown CI job")
    _validate_tree(tree)
    entries = [
        [path, *entry] for path, entry in sorted(tree.items())
        if job in _path_jobs(path)
    ]
    payload = {"schema": INPUT_SCHEMA, "job": job, "entries": entries}
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def fingerprints(tree: Mapping[str, TreeEntry]) -> dict[str, str]:
    return {job: fingerprint_job(job, tree) for job in JOBS}
