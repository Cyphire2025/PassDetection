"""Record reviewed source hashes and runtime facts for the isolated dashboard stack."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/dashboard-qa"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.audit.yml")]


def run(*command: str) -> str:
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def main() -> None:
    if "name: passdetection-audit" not in (ROOT / "docker-compose.audit.yml").read_text():
        raise RuntimeError("Only the isolated audit project is supported")
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
import json, os
from pathlib import Path
import pillow_heif, pypdf
forbidden = [p for p in ['/app/debug','/app/outputs','/app/tests','/app/.venv','/app/.env'] if Path(p).exists()]
result = {'libheif': pillow_heif.libheif_info()['libheif'], 'pypdf': pypdf.__version__, 'uid': os.getuid(), 'forbidden_artifacts': forbidden}
assert not forbidden and result['uid'] != 0
assert result['libheif'] == '1.23.2' and result['pypdf'] == '6.16.1'
print(json.dumps(result))
"""
    frontend_code = """
const fs = require('fs');
const result = {next:require('next/package.json').version, sharp:require('sharp').versions.sharp, libheif:require('sharp').versions.heif, uid:process.getuid(), forbidden_artifacts:['/app/outputs','/app/.env','/app/debug'].filter(p=>fs.existsSync(p))};
if(result.next !== '16.3.3' || result.sharp !== '0.35.4' || result.libheif !== '1.23.2' || result.uid === 0 || result.forbidden_artifacts.length) throw Error('Runtime verification failed');
console.log(JSON.stringify(result));
"""
    backend = json.loads(run(*COMPOSE, "exec", "-T", "backend", "python", "-c", backend_code))
    frontend = json.loads(run(*COMPOSE, "exec", "-T", "frontend", "node", "-e", frontend_code))
    for service, facts in (("backend", backend), ("frontend", frontend)):
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
