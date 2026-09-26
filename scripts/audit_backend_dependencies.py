"""Audit every locked dependency; allow only a current, source-validated exception.

The guard is deliberately conservative, not a proof of arbitrary Python program
reachability. Changes to the lock, reviewed verifier bytes, imports, or owner/date
require a new review. Scanner errors and previously unknown advisories fail closed.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "tooling/dependency-exceptions.json"
FORBIDDEN = {"jose", "ecdsa"}


def imported_modules(source: str, module: str = "") -> set[str]:
    found = set()
    tree = ast.parse(source.lstrip("\ufeff"))
    dynamic_names = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            dynamic_names.update(alias.asname or alias.name for alias in node.names if alias.name == "import_module")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                name = ".".join(module.split(".")[:-node.level] + ([name] if name else []))
            found.add(name)
            found.update(f"{name}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            function = node.func
            dynamic = (isinstance(function, ast.Name) and function.id in dynamic_names) or (
                isinstance(function, ast.Attribute) and function.attr == "import_module")
            if dynamic:
                if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                    raise ValueError("Dynamic imports need explicit reachability review")
                found.add(node.args[0].value)
    return found


def review_errors(policy: dict, *, today: dt.date, lock: bytes,
                  sources: dict[str, str], verifier_sources: dict[str, str],
                  versions: dict[str, str], hashes: dict[str, str]) -> list[str]:
    errors = []
    if policy.get("schema_version") != 1 or len(policy.get("exceptions", [])) != 1:
        return ["Exactly one reviewed exception is supported"]
    exception = policy["exceptions"][0]
    if exception.get("advisory") != "PYSEC-2026-1325" or exception.get("package") != "ecdsa":
        errors.append("Unexpected advisory exception")
    if not exception.get("owner") or not exception.get("rationale") or not exception.get("evidence"):
        errors.append("Exception requires an owner, rationale, and evidence")
    try:
        reviewed = dt.date.fromisoformat(exception["reviewed_on"])
        expiry = dt.date.fromisoformat(exception["expires_on"])
        if reviewed > today or expiry <= today or not 0 < (expiry - reviewed).days <= 90:
            errors.append("Exception is expired, future-dated, or exceeds 90 days")
    except (KeyError, TypeError, ValueError):
        errors.append("Exception review dates are invalid")
    if hashlib.sha256(lock.replace(b"\r\n", b"\n")).hexdigest() != exception.get("runtime_lock_sha256"):
        errors.append("Dependency lock changed: repeat attestation reachability review")
    if versions != exception.get("versions") or hashes != exception.get("source_sha256"):
        errors.append("Reviewed verifier dependency versions or bytes changed")
    entries = set()
    try:
        for source in sources.values():
            imports = imported_modules(source)
            if any(name.split(".")[0] in FORBIDDEN for name in imports):
                errors.append("Application imports a dependency covered by the signing advisory")
            entries.update(name for name in imports if name in verifier_sources)
        if sorted(entries) != exception.get("application_entry_modules"):
            errors.append("Attestation entry modules changed: repeat reachability review")
        pending, visited = list(entries), set()
        while pending:
            module = pending.pop()
            if module in visited:
                continue
            visited.add(module)
            imports = imported_modules(verifier_sources[module], module)
            if any(name.split(".")[0] in FORBIDDEN for name in imports):
                errors.append("Application verifier path reaches jose/ecdsa")
            for name in imports | {module.rpartition(".")[0]}:
                if name in verifier_sources and name not in visited:
                    pending.append(name)
    except (SyntaxError, ValueError):
        errors.append("Import graph cannot be established; manual review required")
    return errors


def installed_evidence() -> tuple[dict, dict, dict]:
    versions, hashes, sources = {}, {}, {}
    for package in ("pyattest", "python-jose", "ecdsa"):
        distribution = importlib.metadata.distribution(package)
        versions[package] = distribution.version
        digest = hashlib.sha256()
        for file in sorted(file for file in distribution.files or [] if str(file).endswith(".py")):
            name = str(file).replace("\\", "/")
            content = Path(distribution.locate_file(file)).read_bytes().replace(b"\r\n", b"\n")
            digest.update(name.encode() + b"\0" + content + b"\0")
            if package == "pyattest":
                module = name[:-3].replace("/", ".").removesuffix(".__init__")
                sources[module] = content.decode("utf-8")
        hashes[package] = digest.hexdigest()
    return versions, hashes, sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--sbom", type=Path)
    parser.add_argument("--image-report", type=Path, help="Gate a complete Grype JSON report after validating the same exception")
    parser.add_argument("--image", help="Execute backend advisory probes against the exact scanned local image")
    parser.add_argument("--image-receipt", type=Path)
    args = parser.parse_args()
    try:
        policy = json.loads(POLICY.read_text())
        versions, hashes, verifier_sources = installed_evidence()
        errors = review_errors(policy, today=dt.datetime.now(dt.timezone.utc).date(),
            lock=(ROOT / "backend/requirements.lock").read_bytes(),
            sources={str(path): path.read_text(encoding="utf-8") for path in (ROOT / "backend/app").rglob("*.py")},
            verifier_sources=verifier_sources, versions=versions, hashes=hashes)
        if errors:
            raise ValueError("; ".join(errors))
        print("Dependency exception owner, expiry, lock, source bytes and reachable verifier imports verified", flush=True)
        if args.image_report:
            report = json.loads(args.image_report.read_text())
            if not isinstance(report.get("matches"), list) or not isinstance(report.get("descriptor"), dict):
                raise ValueError("Full-image scan report is missing required fields")
            exception = policy["exceptions"][0]
            allowed = {exception["advisory"], *exception["aliases"]}
            scoped = set()
            if args.image:
                from image_advisory_policy import validate_runtime_conditions
                scoped = validate_runtime_conditions(report, args.image, args.image_receipt)
            blocked = []
            for match in report["matches"]:
                vulnerability, artifact = match["vulnerability"], match["artifact"]
                if vulnerability["severity"].lower() not in {"high", "critical"}:
                    continue
                if vulnerability["id"] in allowed and artifact["name"] == "ecdsa" and artifact["version"] == exception["versions"]["ecdsa"]:
                    continue
                if (vulnerability["id"], artifact["name"], artifact["version"]) in scoped:
                    continue
                blocked.append(f"{vulnerability['id']} in {artifact['name']} {artifact['version']}")
            if blocked:
                raise ValueError(f"Full image contains {len(blocked)} unaccepted high/critical matches; examples: " + "; ".join(blocked[:8]) + "; inspect the complete JSON report")
            print("Full image high/critical vulnerability gate passed")
            return 0
        if args.check_only:
            return 0
        command = [sys.executable, "-m", "pip_audit", "-r", str(ROOT / "backend/requirements.lock"),
                   "--require-hashes", "--disable-pip", "--ignore-vuln", policy["exceptions"][0]["advisory"]]
        if args.sbom:
            command.extend(["--format", "cyclonedx-json", "--output", str(args.sbom)])
        return subprocess.run(command, check=False).returncode
    except (OSError, ValueError, importlib.metadata.PackageNotFoundError) as error:
        parser.error(str(error))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
