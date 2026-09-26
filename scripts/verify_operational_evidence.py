"""Fail closed on missing/stale operational receipts; never substitutes for a drill.

This verifies operator-supplied evidence structure, chronology and file hashes.
An independent operator must still review the actual receipts and infrastructure.
The script never deploys, contacts recipients, connects to production, or makes
an unsupported claim that a provider configuration exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit


def validate(document: dict, directory: Path, *, now: datetime) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    def named(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {"unknown", "tbd", "todo", "example", "replace_me"}

    def dated(value: object, label: str) -> datetime | None:
        try:
            date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if date.tzinfo is None:
                raise ValueError("Timezone required")
            require(now - timedelta(days=35) <= date <= now, f"{label}: receipt must be within the last 35 days, not in the future")
            return date
        except (TypeError, ValueError):
            errors.append(f"{label}: timezone-aware receipt timestamp required")
            return None

    def receipt(value: object, label: str) -> None:
        if not isinstance(value, dict):
            errors.append(f"{label}: hashed evidence file required")
            return
        raw_path, expected = value.get("path"), value.get("sha256")
        if not isinstance(raw_path, str) or not raw_path or not isinstance(expected, str):
            errors.append(f"{label}: path and SHA-256 required")
            return
        path = (directory / raw_path).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            errors.append(f"{label}: evidence must exist inside the supplied evidence directory")
            return
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        require(digest == expected.lower(), f"{label}: evidence file checksum mismatch")

    require(document.get("schema_version") == 1, "schema_version must equal 1")
    require(document.get("environment") == "production", "Evidence must explicitly identify production")
    require(document.get("synthetic") is False, "Synthetic CI/local evidence cannot close the operational gate")
    require(named(document.get("reviewed_by")), "Named independent evidence reviewer required")
    reviewed = dated(document.get("reviewed_at"), "reviewed_at")
    primary_domain = document.get("application_failure_domain")
    require(named(primary_domain), "Application failure domain must be identified")
    monitoring = document.get("monitoring")
    recovery = document.get("recovery")
    if not isinstance(monitoring, dict) or not isinstance(recovery, dict):
        return [*errors, "Both monitoring and recovery evidence records are required"]
    for section, value in (("monitoring", monitoring), ("recovery", recovery)):
        domain = value.get("external_failure_domain")
        require(named(domain) and domain != primary_domain, f"{section}: independently identified off-host failure domain required")
        receipt(value.get("receipt"), section)
    responders = [monitoring.get("primary_responder"), monitoring.get("backup_responder")]
    require(all(named(value) for value in responders) and responders[0] != responders[1], "Distinct named primary and backup responders required")
    try:
        probe = urlsplit(str(monitoring.get("external_probe_url", "")))
        require(probe.scheme == "https" and bool(probe.hostname) and probe.hostname not in {"localhost", "127.0.0.1"}
                and not probe.username and not probe.password, "External HTTPS probe URL without credentials required")
    except ValueError:
        errors.append("External HTTPS probe URL is invalid")
    for key, minimum in (("metrics_retention_days", 30), ("event_retention_days", 90)):
        value = monitoring.get(key)
        require(type(value) is int and value >= minimum, f"monitoring.{key} must meet the documented {minimum}-day initial minimum")
    times = [dated(monitoring.get(key), f"monitoring.{key}") for key in ("injected_at", "received_at", "acknowledged_at")]
    if all(value is not None for value in times):
        require(times == sorted(times), "Alert injection, receipt and acknowledgement must be in chronological order")
        if reviewed is not None:
            require(times[-1] <= reviewed, "Evidence review must follow alert acknowledgement")
    restored = dated(recovery.get("completed_at"), "recovery.completed_at")
    if restored is not None and reviewed is not None:
        require(restored <= reviewed, "Evidence review must follow recovery completion")
    for key in ("encrypted_off_host_backup", "backup_deletion_protected", "pitr_verified",
                "database_object_checksums_reconciled", "restored_application_verified", "redis_domains_reconciled"):
        require(recovery.get(key) is True, f"recovery.{key}: actual successful drill evidence required")
    for metric in ("rpo_seconds", "rto_seconds"):
        observed, approved = recovery.get(metric), recovery.get(f"approved_{metric}")
        require(type(observed) is int and observed >= 0 and type(approved) is int and approved >= 0
                and observed <= approved, f"recovery.{metric}: measured result must meet an explicit approved objective")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="Private operations receipt JSON; do not commit recipient/backup details")
    arguments = parser.parse_args()
    try:
        document = json.loads(arguments.evidence.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise TypeError("Evidence must be a JSON object")
        errors = validate(document, arguments.evidence.parent, now=datetime.now(UTC))
    except (OSError, ValueError, TypeError) as error:
        print(f"Operational evidence gate OPEN: {error}")
        return 1
    if errors:
        print("Operational evidence gate OPEN:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Supplied operational receipts are complete, timely and checksum-valid; independent content review remains required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
