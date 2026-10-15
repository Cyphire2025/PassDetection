"""Record reviewed source hashes and runtime facts for the isolated dashboard stack."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/dashboard-qa"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.audit.yml")]
REVIEWED_LIBHEIF = {"backend": "1.23.2", "frontend": "1.23.5"}


def reviewed_runtime_versions(root: Path) -> dict[str, dict[str, str]]:
    lock = (root / "backend/requirements.lock").read_text(encoding="utf-8")
    matches = re.findall(r"^pypdf==([0-9][A-Za-z0-9.!+_-]*)[ \t]*(?:\\)?$", lock, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("The reviewed runtime lock must contain one exact pypdf pin")
    packages = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))["packages"]
    frontend = {name: packages[f"node_modules/{name}"]["version"] for name in ("next", "sharp")}
    if any(not isinstance(version, str) or not version for version in frontend.values()):
        raise ValueError("The frontend lock must contain exact Next and Sharp versions")
    return {"backend": {"pypdf": matches[0]}, "frontend": frontend}


def validate_runtime_facts(service: str, facts: dict, expected: dict[str, str]) -> None:
    for package, version in expected.items():
        if facts.get(package) != version:
            raise ValueError(f"{service} {package} differs from the reviewed runtime lock")
    # Native parser provenance is a separate reviewed invariant; Python/Node
    # package lock versions do not identify their embedded libheif bytes.
    if facts.get("libheif") != REVIEWED_LIBHEIF[service]:
        raise ValueError(f"{service} libheif differs from the reviewed native parser")
    if facts.get("uid") in (None, 0) or facts.get("forbidden_artifacts") != []:
        raise ValueError(f"{service} runtime isolation or artifact exclusion failed")
    if facts.get("build_tools") != []:
        raise ValueError(f"{service} contains build-only tooling")


def run(*command: str) -> str:
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def main() -> None:
    if "name: passdetection-audit" not in (ROOT / "docker-compose.audit.yml").read_text():
        raise RuntimeError("Only the isolated audit project is supported")
    expected = reviewed_runtime_versions(ROOT)
    run("git", "-c", "core.safecrlf=false", "diff", "--check")
    changed = sorted(set(run("git", "ls-files", "--modified", "--others", "--exclude-standard", "-z").split("\0")))
    files = []
    for relative in changed:
        if not relative:
            continue
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT):
            raise RuntimeError("Source path escaped the workspace")
        files.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None})
    backend_code = """
import importlib.util, json, os
from pathlib import Path
import pillow_heif, pypdf
forbidden = [p for p in ['/app/debug','/app/outputs','/app/tests','/app/.venv','/app/.env'] if Path(p).exists()]
tools = [name for name in ('setuptools', 'wheel') if importlib.util.find_spec(name) is not None]
result = {'libheif': pillow_heif.libheif_info()['libheif'], 'pypdf': pypdf.__version__, 'uid': os.getuid(), 'forbidden_artifacts': forbidden, 'build_tools': tools}
print(json.dumps(result))
"""
    frontend_code = """
const fs = require('fs');
const result = {next:require('next/package.json').version, sharp:require('sharp').versions.sharp, libheif:require('sharp').versions.heif, uid:process.getuid(), forbidden_artifacts:['/app/outputs','/app/.env','/app/debug','/app/tooling/npm-security','/app/scripts/patch-npm-toolchain.mjs'].filter(p=>fs.existsSync(p)), build_tools:['/usr/local/lib/node_modules/npm','/usr/local/lib/node_modules/corepack','/opt/yarn-v1.22.22'].filter(p=>fs.existsSync(p))};
console.log(JSON.stringify(result));
"""
    backend = json.loads(run(*COMPOSE, "exec", "-T", "backend", "python", "-c", backend_code))
    frontend = json.loads(run(*COMPOSE, "exec", "-T", "frontend", "node", "-e", frontend_code))
    for service, facts in (("backend", backend), ("frontend", frontend)):
        validate_runtime_facts(service, facts, expected[service])
        container = run(*COMPOSE, "ps", "-q", service)
        facts["image_id"] = run("docker", "inspect", "--format", "{{.Image}}", container)
        (OUTPUT / f"{service}-image-check.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
        "base_head": run("git", "rev-parse", "HEAD"),
        "working_tree_is_dirty": bool(files),
        "script_performs_commits_or_pushes": False,
        "source_files": files,
        "runtime_images": {"backend": backend, "frontend": frontend},
    }
    (OUTPUT / "release-evidence.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Recorded {len(files)} changed-source hashes and both non-root runtime images")


if __name__ == "__main__":
    main()
