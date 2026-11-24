"""Production browser qualification with isolated local fixtures and source fence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
OUT = ROOT / "docs/audit/dashboard-2026-10-30/final-retained-frontend-20261101-002"
WORK = ROOT / ".tmp/final-frontend-integration"
NODE = Path("C:/Users/nipun/AppData/Local/Programs/node-v24.21.0-win-x64/node.exe")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, data: object) -> None:
    (OUT / name).write_bytes((json.dumps(data, indent=2) + "\n").encode())


def fence() -> dict[str, str]:
    names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "frontend"], cwd=ROOT).decode().split("\0")
    return {name: sha(ROOT / name) for name in sorted(set(names)) if name and (ROOT / name).is_file()}


qualification = json.loads((OUT / "test-only-amendment/verification.json").read_bytes())
assert qualification["all_commands_passed"] is True
assert qualification["application_source_changes"] == 0
assert qualification["all_original_non_Node_build_commands_passed"] is True
assert (FRONTEND / ".next/BUILD_ID").read_text().strip() == qualification["build_id"]
snapshot = OUT / "test-only-amendment/source-fence-after.json"
assert sha(snapshot) == qualification["source_fence_sha256"]
initial = json.loads(snapshot.read_bytes())
if fence() != initial:
    raise SystemExit("Source drift before browser run")
for port in (3100, 3199):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"Refusing to reuse occupied fixture port {port}")
standalone = (FRONTEND / ".next/standalone").resolve()
if not standalone.is_relative_to(FRONTEND.resolve()) or not (standalone / "server.js").is_file():
    raise SystemExit("Qualified standalone output missing")
for source, target in ((FRONTEND / ".next/static", standalone / ".next/static"),
                       (FRONTEND / "public", standalone / "public")):
    if not target.resolve().is_relative_to(standalone):
        raise SystemExit("Generated copy boundary violation")
    shutil.copytree(source, target, dirs_exist_ok=True)
branding_names = ["company-logo-preview.png", "all-groups-desktop.png", "company-logo-editor.png",
                  "group-banner-desktop.png", "group-banner-mobile.png", "visa-company-logo.png",
                  "group-background-editor.png", "group-background-desktop.png", "group-background-mobile.png",
                  "group-background-editor-mobile.png", "group-banner-first-editor-1440.png",
                  "group-banner-first-editor-390.png"]
prior = {}
for name in branding_names:
    path = ROOT / ".tmp/branding-ui" / name
    if path.is_file():
        destination = WORK / "prior-branding-screenshots" / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(path, destination)
        prior[name] = {"sha256": sha(path), "preserved_at": str(destination)}
write("preserved-prior-branding-screenshots.json", prior)
env = {key: value for key, value in os.environ.items()
       if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LOCALAPPDATA",
                          "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)", "SYSTEMDRIVE", "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH",
                          "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PATHEXT", "PATH"}}
env.update(PATH=str(NODE.parent) + os.pathsep + env.get("PATH", ""), API_BASE_URL="http://127.0.0.1:3199",
           NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:3199", NEXT_PUBLIC_APP_URL="http://127.0.0.1:3100",
           NEXT_PUBLIC_DEV_APP_URL="", NEXT_TELEMETRY_DISABLED="1", NO_COLOR="1")
argv = [str(NODE), "node_modules/@playwright/test/cli.js", "test", "--config", str(WORK / "production.config.ts")]
print("START all retained production browser specs plus nonce/rewrite controls", flush=True)
started = time.monotonic()
with (OUT / "production-browser.log").open("wb") as output:
    completed = subprocess.run(argv, cwd=FRONTEND, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=5400)
current = fence()
drift = {key: [initial.get(key), current.get(key)] for key in initial.keys() | current.keys() if initial.get(key) != current.get(key)}
screenshots = {}
for name in branding_names:
    source = ROOT / ".tmp/branding-ui" / name
    if source.is_file():
        target = OUT / "branding-screenshots" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        screenshots[name] = {"sha256": sha(target), "path": target.relative_to(ROOT).as_posix()}
write("production-browser-command.json", {"argv": argv, "exit_code": completed.returncode,
      "seconds": round(time.monotonic() - started, 3), "source_drift": drift,
      "log_sha256": sha(OUT / "production-browser.log"), "branding_screenshots": screenshots,
      "limits": "Chromium production build with synthetic API/browser fixtures. No actual backend/service/provider/mobile device or VPS qualification."})
print(json.dumps({"exit_code": completed.returncode, "source_drift": len(drift)}), flush=True)
