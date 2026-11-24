from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
stage = Path(__file__).resolve().parent
audit = root / "docs/audit/dashboard-2026-10-30/final-fixture-warning-repair"
audit.mkdir(parents=True, exist_ok=True)
work = root / ".tmp/final-fixture-warning-repair"
work.mkdir(parents=True, exist_ok=True)
node = Path("C:/Users/nipun/AppData/Local/Programs/node-v24.21.0-win-x64/node.exe")
proposal = json.loads((stage / "proposal.json").read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


parent_fence_path = root / "docs/audit/dashboard-2026-10-30/final-retained-frontend-20261101-002/source-fence-after.json"
parent_fence = json.loads(parent_fence_path.read_text(encoding="utf-8"))
assert not any(Path(path).name.startswith(".env") for path in parent_fence)
current_before = {path: sha(root / path) for path in parent_fence}
write(audit / "source-fence-before.json", current_before)
write(audit / "parent-baseline-drift-at-start.json", {path: {"parent": digest, "current": current_before[path]} for path, digest in parent_fence.items() if digest != current_before[path]})

for row in proposal["files"]:
    path = root / row["path"]
    assert sha(path) == row["before_sha256"], row["path"]
    candidate = stage / row["path"]
    assert sha(candidate) == row["candidate_sha256"]
    inverse = candidate.read_bytes().decode("utf-8")
    for change in reversed(row["replacements"]):
        assert inverse.count(change["after"]) == 1
        inverse = inverse.replace(change["after"], change["before"], 1)
    assert hashlib.sha256(inverse.encode("utf-8")).hexdigest() == row["before_sha256"]
    before_copy = audit / "before-source" / row["path"]
    after_copy = audit / "current-source-snapshots" / row["path"]
    before_copy.parent.mkdir(parents=True, exist_ok=True)
    after_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, before_copy)
    shutil.copyfile(candidate, path)
    shutil.copyfile(path, after_copy)

for name in ["proposal.json", "assertion-preservation.json"]:
    shutil.copyfile(stage / name, audit / name)
tests = [row["path"].removeprefix("frontend/") for row in proposal["files"]]
tsconfig = work / "tsconfig.json"
write(tsconfig, {
    "extends": "../../frontend/tsconfig.json",
    "compilerOptions": {"incremental": False, "noEmit": True},
    "include": ["../../frontend/vitest.setup.ts", *["../../frontend/" + path for path in tests]],
    "exclude": ["../../frontend/node_modules", "../../frontend/.next"],
})
keys = {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PATHEXT", "PATH", "SYSTEMDRIVE", "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH"}
env = {key: value for key, value in os.environ.items() if key.upper() in keys}
env.update(PATH=str(node.parent) + os.pathsep + env.get("PATH", ""), API_BASE_URL="http://127.0.0.1:3199", NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:3199", NEXT_TELEMETRY_DISABLED="1", NO_COLOR="1")
commands = {
    "affected-vitest": [str(node), "node_modules/vitest/vitest.mjs", "run", *tests, "--config", str(root / ".tmp/banner-crop-target/vitest.config.mts"), "--maxWorkers=1", "--pool=threads"],
    "scoped-eslint": [str(node), "node_modules/eslint/bin/eslint.js", *tests, "--max-warnings=0"],
    "scoped-types": [str(node), "node_modules/typescript/bin/tsc", "--project", str(tsconfig), "--noEmit", "--incremental", "false"],
}
results = {}
for name, argv in commands.items():
    started = time.monotonic()
    with (audit / (name + ".stdout.log")).open("wb") as stdout, (audit / (name + ".stderr.log")).open("wb") as stderr:
        result = subprocess.run(argv, cwd=root / "frontend", env=env, stdout=stdout, stderr=stderr, timeout=120)
    results[name] = {"argv": argv, "cwd": "frontend", "exit_code": result.returncode, "seconds": time.monotonic() - started, "stdout": name + ".stdout.log", "stderr": name + ".stderr.log", "stderr_bytes": (audit / (name + ".stderr.log")).stat().st_size}
    write(audit / (name + "-command.json"), results[name])
    print(name, result.returncode, flush=True)
current_after = {path: sha(root / path) for path in parent_fence}
write(audit / "source-fence-after.json", current_after)
changed = {path: {"before": digest, "after": current_after[path]} for path, digest in current_before.items() if digest != current_after[path]}
write(audit / "source-delta.json", changed)
own_paths = {row["path"] for row in proposal["files"]}
runtime_drift = {path: delta for path, delta in changed.items() if path not in own_paths and ".test." not in path and ".spec." not in path}
write(audit / "results.json", {"commands": results, "own_test_hashes_match_candidates": all(current_after[row["path"]] == row["candidate_sha256"] for row in proposal["files"]), "runtime_drift": runtime_drift, "unrelated_source_deltas": {path: delta for path, delta in changed.items() if path not in own_paths}, "no_console_filtering": True, "envDir": False})
assert not runtime_drift
assert all(result["exit_code"] == 0 for result in results.values())
assert all(current_after[row["path"]] == row["candidate_sha256"] for row in proposal["files"])
print(json.dumps({"changed": list(changed), "all_checks_passed": True, "stderr_bytes": {name: result["stderr_bytes"] for name, result in results.items()}}, indent=2))
