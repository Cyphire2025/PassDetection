"""Host binding for the exact additive workspace branding migration."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / 'backend/scripts/workspace_branding_release.py'
_SPEC = importlib.util.spec_from_file_location('workspace_branding_contract', _PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError('Workspace branding contract unavailable')
_POLICY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_POLICY)
SOURCE, TARGET, KIND = _POLICY.SOURCE, _POLICY.TARGET, _POLICY.KIND
validate_contract = _POLICY.validate_contract


def source_contract(root: Path) -> dict:
    manifest = json.loads((root / 'backend/app/core/config/release_manifest.json').read_text('utf-8'))
    if (manifest.get('deployment_kind'), manifest.get('previous_schema_revision'), manifest.get('schema_revision')) != (KIND, SOURCE, TARGET):
        raise ValueError('exact_workspace_branding_release_required')
    return {**_POLICY.POLICY, 'migrations': _POLICY.migration_entries(root / 'backend')}
