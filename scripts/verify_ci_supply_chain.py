"""Fail closed on mutable CI executables and accidental dependency refreshes."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
BACKEND_ROOT = ROOT / "backend"
REMOTE_ACTION = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)@([^\s#]+)")
IMMUTABLE_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def policy_errors(workflow_sources: dict[str, str]) -> list[str]:
    errors: list[str] = []
    combined = "\n".join(workflow_sources.values())
    for name, source in sorted(workflow_sources.items()):
        for line_number, line in enumerate(source.splitlines(), start=1):
            match = REMOTE_ACTION.match(line)
            if match and not IMMUTABLE_COMMIT.fullmatch(match.group(2)):
                errors.append(
                    f"{name}:{line_number} remote action {match.group(1)!r} must use a full commit SHA"
                )
        lowered = source.lower()
        if "pod install --repo-update" in lowered:
            errors.append(f"{name} must not refresh CocoaPods indexes during verification or release")
        if "pull_request_target" in lowered:
            errors.append(f"{name} must not execute this repository through pull_request_target")
        if re.search(r"permissions:\s*write-all", source, re.IGNORECASE):
            errors.append(f"{name} must use explicit least-privilege permissions")
        if re.search(r"curl[^\n|]*\|\s*(?:ba)?sh\b", source, re.IGNORECASE):
            errors.append(f"{name} must not pipe network content directly into a shell")

    required_evidence = {
        "mobile JavaScript SBOM": "mobile-sbom.cdx.json",
        "frontend JavaScript SBOM": "frontend-sbom.cdx.json",
        "backend Python SBOM": "backend-sbom.cdx.json",
        "mobile release-Hermes contracts": "npm run e2e:contracts",
        "mobile high-risk module budgets": "npm run maintainability:check",
        "mobile reviewed coverage floor": "npm run test:coverage",
    }
    for description, marker in required_evidence.items():
        if marker not in combined:
            errors.append(f"CI is missing the {description} gate ({marker})")
    return errors


def main() -> None:
    sources = {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(WORKFLOW_ROOT.glob("*.y*ml"))
    }
    errors = policy_errors(sources)
    backend_lock = BACKEND_ROOT / "requirements.lock"
    backend_dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    combined_workflows = "\n".join(sources.values())
    if not backend_lock.is_file():
        errors.append("backend/requirements.lock is missing")
    else:
        lock_source = backend_lock.read_text(encoding="utf-8")
        if "--generate-hashes" not in lock_source or "--hash=sha256:" not in lock_source:
            errors.append("backend/requirements.lock must be a hash-verified generated lock")
    if "COPY requirements.lock" not in backend_dockerfile:
        errors.append("backend Dockerfile must copy requirements.lock")
    if "--require-hashes -r requirements.lock" not in backend_dockerfile:
        errors.append("backend Dockerfile must install the production lock with --require-hashes")
    if "uv pip compile requirements.txt" not in combined_workflows:
        errors.append("CI must regenerate and diff-check the backend production lock")
    if "pip install --require-hashes -r requirements.lock" not in combined_workflows:
        errors.append("backend CI tests must install the hash-verified production lock")
    if "pip-audit -r requirements.lock --require-hashes --disable-pip" not in combined_workflows:
        errors.append("backend dependency audit must consume the reviewed lock without re-resolution")
    if errors:
        raise SystemExit("CI supply-chain policy failed:\n- " + "\n- ".join(errors))
    print("CI supply-chain policy passed: actions are immutable and SBOM gates are present.")


if __name__ == "__main__":
    main()
