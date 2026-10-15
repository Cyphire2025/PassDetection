"""Host adapter for the exact document-distribution contract in the backend image."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "backend/scripts/document_distribution_release.py"
_SPEC = importlib.util.spec_from_file_location("document_distribution_release_policy", _PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("Document distribution release policy is unavailable")
_POLICY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_POLICY)
KIND, SOURCE, CHAIN, TARGET, POLICY = (
    _POLICY.KIND, _POLICY.SOURCE, _POLICY.CHAIN, _POLICY.TARGET, _POLICY.POLICY
)
validate_contract = _POLICY.validate_contract


def source_contract(root: Path) -> dict:
    manifest = json.loads((root / "backend/app/core/config/release_manifest.json").read_text("utf-8"))
    if (manifest.get("deployment_kind"), manifest.get("previous_schema_revision"),
            manifest.get("schema_revision")) != (KIND, SOURCE, TARGET):
        raise ValueError("Exact document distribution source and target schema required")
    return {**POLICY, "migrations": _POLICY.migration_entries(root / "backend")}
