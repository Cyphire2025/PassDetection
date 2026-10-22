"""Standalone QA entrypoints resolve their ORM without application imports."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class QualificationSeedRegistryTests(unittest.TestCase):
    def test_standalone_entrypoints_resolve_relationships_and_foreign_keys(self) -> None:
        environment = {
            **os.environ,
            "APP_ENV": "development",
            "APP_SECRET_KEY": "qualification-registry-test-only-not-for-deployment",
            "POSTGRES_DB": "passdetection_ci_registry",
            "POSTGRES_PASSWORD": "registry-test-only",
            "S3_ACCESS_KEY_ID": "registry-test-only",
            "S3_SECRET_ACCESS_KEY": "registry-test-only",
            "PYTHONPATH": str(ROOT / "backend"),
            "PYTHONUTF8": "1",
        }
        code = """
import runpy
import sys
from sqlalchemy.orm import configure_mappers
runpy.run_path(sys.argv[1], run_name='qualification_seed_registry_test')
from app.infrastructure.database.models import Base
configure_mappers()
assert 'client_organizations' in Base.metadata.tables
for table in Base.metadata.tables.values():
    for foreign_key in table.foreign_keys:
        assert foreign_key.column is not None
"""
        # A fresh directory prevents loading a developer's .env; no connections
        # or seed writes are made while configuring mapper metadata.
        for entrypoint in ("seed_enterprise_browser_stack.py", "qualification_restored_objects.py"):
            with self.subTest(entrypoint=entrypoint), tempfile.TemporaryDirectory(prefix="passdetection-qa-registry-") as directory:
                result = subprocess.run(
                    [sys.executable, "-c", code, str(ROOT / "scripts/qa" / entrypoint)],
                    cwd=directory, env=environment, capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
