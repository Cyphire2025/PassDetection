"""Retain the historical company rollout in tests after the active schema advances."""
from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from release_companies_traveller_contract import CHAIN, KIND, SOURCE, TARGET


@contextmanager
def company_source():
    repository = Path(__file__).resolve().parents[1]
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest = root / "backend/app/core/config/release_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"deployment_kind": KIND,
            "previous_schema_revision": SOURCE, "schema_revision": TARGET}), encoding="utf-8")
        for revision in CHAIN:
            relative = f"backend/alembic/versions/{revision}.py"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repository / relative, target)
        yield root
