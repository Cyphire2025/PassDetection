"""Require owned, dated, bounded and evidence-linked engineering claims."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_claims(data: dict, root: Path, today: dt.date) -> list[str]:
    errors = []
    identifiers = set()
    for claim in data.get("claims", []):
        identifier = claim.get("id", "missing")
        if identifier in identifiers:
            errors.append(f"{identifier}: duplicate claim")
        identifiers.add(identifier)
        if not all(claim.get(key) for key in ("owner", "scope", "limitation", "evidence")):
            errors.append(f"{identifier}: owner, scope, limitation and evidence are required")
        if claim.get("status") not in {"verified-local", "implemented-unverified-external", "deferred", "not-claimed"}:
            errors.append(f"{identifier}: unsupported evidence status")
        try:
            reviewed, expires = (dt.date.fromisoformat(claim[key]) for key in ("reviewed_on", "review_by"))
            if reviewed > today or expires <= today or not 0 < (expires - reviewed).days <= 90:
                errors.append(f"{identifier}: stale/future claim or review period exceeds 90 days")
        except (KeyError, TypeError, ValueError):
            errors.append(f"{identifier}: invalid review dates")
        for evidence in claim.get("evidence", []):
            path = (root / evidence.get("path", "")).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                errors.append(f"{identifier}: evidence path does not exist inside the repository")
            elif hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != evidence.get("sha256"):
                errors.append(f"{identifier}: evidence changed; review its scope before refreshing the claim")
    if not identifiers:
        errors.append("No accountable claims are registered")
    return errors


def main() -> None:
    data = json.loads((ROOT / "docs/engineering-claims.json").read_text())
    errors = validate_claims(data, ROOT, dt.datetime.now(dt.timezone.utc).date())
    if errors:
        raise SystemExit("Documentation claims rejected:\n- " + "\n- ".join(errors))
    print(f"Documentation claim ownership, review expiry and evidence fingerprints verified ({len(data['claims'])} claims)")


if __name__ == "__main__":
    main()
