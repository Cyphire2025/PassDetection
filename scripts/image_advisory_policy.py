"""Validate scoped full-image dispositions against the exact scanned image.

No advisory is accepted just because the distribution has not issued an update.
Every listed package/version also requires live negative probes and reviewed
deployment preconditions. Unlisted matches fail in the caller.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A new JSON entry cannot grant itself an exception without a corresponding
# executable condition and code review here. These IDs share the probes below.
CHECKED_DISPOSITIONS = {
    **dict.fromkeys(("CVE-2026-66046", "CVE-2026-76956", "CVE-2026-76957", "CVE-2026-93990", "CVE-2026-82049"), "fixed_by_backport"),
    **dict.fromkeys(("CVE-2025-69720", "CVE-2026-52490", "CVE-2026-82560", "CVE-2026-9538", "CVE-2026-54370"), "affected_component_absent"),
    **dict.fromkeys(("CVE-2026-19499", "CVE-2026-5435"), "affected_code_not_used"),
    **dict.fromkeys(("CVE-2026-76642", "CVE-2026-78408", "CVE-2026-78409", "CVE-2026-78410", "CVE-2026-54369"), "mitigated_not_patched"),
    "CVE-2026-85091": "incorrect_affected_range",
}


def validate_report_identity(report: dict, inspected: dict) -> str:
    target = report["source"]["target"]
    raw = base64.b64decode(target["config"], validate=True)
    identifier = "sha256:" + hashlib.sha256(raw).hexdigest()
    config = json.loads(raw)
    if identifier != target["imageID"] or config["config"] != inspected["Config"]:
        raise ValueError("Scanner and executed image configuration differ")
    if config["rootfs"]["diff_ids"] != inspected["RootFS"]["Layers"]:
        raise ValueError("Scanner and executed image filesystem layers differ")
    if config["architecture"] != inspected["Architecture"] or config["os"] != inspected["Os"]:
        raise ValueError("Scanner and executed image platform differ")
    return identifier


def validate_policy(policy: dict, today: dt.date) -> set[tuple[str, str, str]]:
    accepted = set()
    if policy.get("schema_version") != 1 or not policy.get("entries"):
        raise ValueError("Missing scoped image advisory review")
    for entry in policy["entries"]:
        start, end = (dt.date.fromisoformat(entry[key]) for key in ("reviewed_on", "expires_on"))
        if not entry.get("owner") or not entry.get("evidence") or not entry.get("condition"):
            raise ValueError("Image advisory requires accountable owner, evidence and conditions")
        if not start <= today < end or not 0 < (end - start).days <= 90:
            raise ValueError("Image advisory review expired or is future dated")
        if entry["disposition"] not in {"fixed_by_backport", "affected_component_absent", "affected_code_not_used", "incorrect_affected_range", "mitigated_not_patched"}:
            raise ValueError("Unsupported image disposition")
        if CHECKED_DISPOSITIONS.get(entry["advisory"]) != entry["disposition"]:
            raise ValueError("Advisory has no matching executable runtime condition")
        for package in entry["packages"]:
            key = (entry["advisory"], package["name"], package["version"])
            if key in accepted:
                raise ValueError("Duplicate image advisory review")
            accepted.add(key)
    return accepted


def validate_runtime_conditions(report: dict, image: str, receipt: Path | None = None) -> set[tuple[str, str, str]]:
    inspected = json.loads(subprocess.check_output(["docker", "image", "inspect", image], text=True))[0]
    identifier = validate_report_identity(report, inspected)
    # Use the immutable local identifier throughout so a changed mutable tag
    # cannot select different bytes after the scanner/identity check.
    arguments = ["docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges:true", "--mount",
                 f"type=bind,source={ROOT / 'scripts/qa'},target=/qa,readonly", "--entrypoint", "python", inspected["Id"]]
    native = json.loads(subprocess.check_output([*arguments, "/qa/probe_image_advisory_conditions.py"], text=True))
    smoke = json.loads(subprocess.check_output([*arguments, "/qa/qualify_runtime_image.py",
        "--require-no-video", "--require-patched-parsers"], text=True).splitlines()[-1])
    from image_runtime_policy import validate_process_isolation
    from verify_compose_runtime import (
        BASE_COMPOSE,
        PROD_COMPOSE,
        STORAGE_COMPOSE,
        _render_compose,
    )
    validate_process_isolation(_render_compose(BASE_COMPOSE, PROD_COMPOSE, STORAGE_COMPOSE)["services"],
                               storage_directory=str(ROOT / "tmp/compose-contract"))
    policy = json.loads((ROOT / "tooling/image-advisory-dispositions.json").read_text())
    accepted = validate_policy(policy, dt.datetime.now(dt.timezone.utc).date())
    if receipt:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        native.pop("native_inventory")  # Full local probe remains available separately.
        receipt.write_text(json.dumps({"result": "passed", "image_config_sha256": identifier,
            "image_id": inspected["Id"], "scan_sha256": hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
            "policy_sha256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
            "native_conditions": native, "runtime_smoke": smoke,
            "limitation": "Advisory-specific dispositions, including explicitly mitigated unpatched libraries; this is not a zero-vulnerability claim."}, indent=2) + "\n")
    return accepted
