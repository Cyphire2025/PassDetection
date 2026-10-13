"""Source-bound Full migration preparation; no database or deployment access."""

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from release_companies_traveller_contract import CHAIN, KIND, POLICY, SOURCE, TARGET
from release_manifest import verify_source_defaults
from release_mcp_contract import require_same_schema_artifact, require_source_contract, source_contract, validate_contract
from release_mcp_database import DUMP_COMMAND, MCPDatabaseRelease, ReleaseBindings
from release_traveller_whatsapp import ReleaseError

ROOT = Path(__file__).resolve().parents[1]


def helper():
    spec = importlib.util.spec_from_file_location("companies_upgrade_helper", ROOT / "backend/scripts/release_companies_traveller_upgrade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompanyTravellerReleaseTests(unittest.TestCase):
    def test_current_contract_and_packaged_helper_share_exact_policy(self):
        value = source_contract(ROOT)
        validate_contract(value, TARGET)
        require_source_contract({"deployment": value}, ROOT)
        verify_source_defaults()
        module = helper()
        self.assertEqual(module.POLICY, POLICY)
        self.assertEqual(len(value["migrations"]), 4)
        module.verify_sources(ROOT / "backend", value)
        with self.assertRaises(ValueError):
            require_same_schema_artifact({"deployment": value})

    def test_policy_hash_ancestry_order_and_resume_scope_are_not_relaxable(self):
        value = source_contract(ROOT)
        for key, changed in {
            "version": True, "company_backfill": "match_names", "reuse_authority": "enabled",
            "historical_rows": "retain_some", "automatic_downgrade": True,
            "resume_schema_revisions": [SOURCE], "unknown": "ignored",
        }.items():
            revised = {**copy.deepcopy(value), key: changed}
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_contract(revised, TARGET)
        for index in range(len(CHAIN)):
            for key, changed in {"sha256": "0" * 64, "path": "../../unreviewed.py", "parent": TARGET}.items():
                revised = copy.deepcopy(value)
                revised["migrations"][index][key] = changed
                with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                    helper().verify_sources(ROOT / "backend", revised)
        revised = copy.deepcopy(value)
        revised["migrations"].reverse()
        with self.assertRaises(ValueError):
            validate_contract(revised, TARGET)

    def test_duplicate_identity_source_file_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "backend/app/core/config/release_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"deployment_kind": KIND, "previous_schema_revision": SOURCE, "schema_revision": TARGET}))
            for revision in CHAIN:
                relative = f"backend/alembic/versions/{revision}.py"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, path)
            path.write_bytes(path.read_bytes() + b'\ndown_revision = "unreviewed"\n')
            with self.assertRaises(ValueError):
                source_contract(root)

    def test_each_revision_is_a_separate_call_and_interruption_resumes_after_last_commit(self):
        module = helper()
        state, invoked = [SOURCE], []

        def upgrade(config, revision):
            invoked.append(revision)
            if revision == CHAIN[2]:
                raise RuntimeError("synthetic interruption during concurrent index")
            state[0] = revision

        with self.assertRaises(RuntimeError):
            module.run_revisions("configuration", SOURCE, upgrade, lambda: state[0])
        self.assertEqual(state[0], CHAIN[1])
        self.assertEqual(invoked, list(CHAIN[:3]))
        resumed = []

        def finish(config, revision):
            resumed.append(revision)
            state[0] = revision

        module.run_revisions("configuration", state[0], finish, lambda: state[0])
        self.assertEqual(resumed, list(CHAIN[2:]))
        module.run_revisions("configuration", TARGET, Mock(side_effect=AssertionError), lambda: TARGET)
        with self.assertRaises(ValueError):
            module.run_revisions("configuration", "0128_mcp_document_delivery", finish, lambda: state[0])
        with self.assertRaises(ValueError):
            module.run_revisions("configuration", SOURCE, Mock(), lambda: SOURCE)

    def test_partial_checkpoint_requires_original_source_backup_and_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory).resolve()
            private.chmod(0o700)
            schema, fenced = [SOURCE], [True]

            def fence():
                if not fenced[0]:
                    raise ReleaseError("not_fenced")

            def command(arguments, *, timeout, stdin_file=None, stdout_file=None):
                if arguments == ("sh", "-c", DUMP_COMMAND):
                    stdout_file.write(b"PGDMPsynthetic-company-backup")
                    return ""
                return "TABLE DATA public alembic_version" if arguments == ("pg_restore", "--list") else ""

            release = MCPDatabaseRelease(ROOT, private, ReleaseBindings("a" * 40, "sha256:" + "b" * 64, "c" * 64, "d" * 64),
                database_command=command, verify_fence=fence, read_schema=lambda: schema[0])
            backup = release.backup()
            for revision in CHAIN:
                schema[0] = revision
                plan = release.migration_request(backup)
                self.assertEqual(plan["arguments"][1], "scripts/release_companies_traveller_upgrade.py")
                self.assertFalse(plan["automatic_downgrade"])
                self.assertEqual(plan["proof"]["backup_schema"], SOURCE)
            schema[0] = CHAIN[1]
            with self.assertRaises(ReleaseError):
                release.backup()
            fenced[0] = False
            with self.assertRaises(ReleaseError):
                release.migration_request(backup)
            fenced[0] = True
            (private / (backup["filename"] + ".json")).unlink()
            with self.assertRaises(ReleaseError):
                release.migration_request(backup)


if __name__ == "__main__":
    unittest.main()
