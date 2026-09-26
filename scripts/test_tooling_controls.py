"""Negative controls for dependency exceptions, interpreter selection and replicas."""
import copy
import datetime as dt
import hashlib
import tempfile
import unittest
from pathlib import Path

from audit_backend_dependencies import imported_modules, review_errors
from bootstrap_backend import require_supported_python
from verify_database_deployment_budget import calculate
from verify_documentation_claims import validate_claims


class DependencyExceptionTests(unittest.TestCase):
    def setUp(self):
        self.policy = {"schema_version": 1, "exceptions": [{
            "advisory": "PYSEC-2026-1325", "package": "ecdsa", "owner": "maintainer",
            "rationale": "Apple verifier only", "evidence": "review.md",
            "reviewed_on": "2026-09-26", "expires_on": "2026-12-25",
            "runtime_lock_sha256": hashlib.sha256(b"locked").hexdigest(),
            "versions": {"pyattest": "1"}, "source_sha256": {"pyattest": "reviewed"},
            "application_entry_modules": ["pyattest.apple"],
        }]}
        self.args = {"today": dt.date(2026, 9, 27), "lock": b"locked",
            "sources": {"app.py": "from pyattest.apple import Config"},
            "verifier_sources": {"pyattest": "", "pyattest.apple": "from pyattest.shared import verify",
                              "pyattest.shared": "import cryptography"},
            "versions": {"pyattest": "1"}, "hashes": {"pyattest": "reviewed"}}

    def test_reviewed_apple_path_passes(self):
        self.assertEqual(review_errors(self.policy, **self.args), [])

    def test_expiry_owner_lock_and_package_changes_each_fail(self):
        for key, value in (("expires_on", "2026-09-27"), ("owner", ""),
                           ("runtime_lock_sha256", "changed"), ("versions", {}),
                           ("source_sha256", {}), ("application_entry_modules", [])):
            policy = copy.deepcopy(self.policy)
            policy["exceptions"][0][key] = value
            with self.subTest(key=key):
                self.assertTrue(review_errors(policy, **self.args))

    def test_reachable_indirect_jose_import_fails(self):
        self.args["verifier_sources"]["pyattest.shared"] = "from jose import jws"
        self.assertTrue(review_errors(self.policy, **self.args))

    def test_direct_application_alias_and_dynamic_imports_fail(self):
        for source in ("import ecdsa as ec", "from jose import jwt", "__import__('ecdsa')", "importlib.import_module(name)",
                       "from importlib import import_module as load; load('ecdsa')", "from importlib import import_module as load; load(name)"):
            self.args["sources"]["bad.py"] = source
            with self.subTest(source=source):
                self.assertTrue(review_errors(self.policy, **self.args))

    def test_unreachable_google_module_does_not_invent_reachability(self):
        self.args["verifier_sources"]["pyattest.google"] = "from jose import jws"
        self.assertEqual(review_errors(self.policy, **self.args), [])

    def test_relative_import_is_resolved(self):
        self.assertIn("pyattest.shared", imported_modules("from .shared import verify", "pyattest.apple"))


class CapacityTests(unittest.TestCase):
    def setUp(self):
        env = {"POSTGRES_SERVER_MAX_CONNECTIONS": "100", "POSTGRES_RESERVED_CONNECTIONS": "10",
               "POSTGRES_API_CONNECTION_BUDGET": "80", "POSTGRES_POOL_PROFILE": "api",
               "WEB_CONCURRENCY": "4", "POSTGRES_API_POOL_SIZE": "8", "POSTGRES_API_MAX_OVERFLOW": "2"}
        worker = {**env, "POSTGRES_POOL_PROFILE": "worker", "POSTGRES_WORKER_POOL_SIZE": "1", "POSTGRES_WORKER_MAX_OVERFLOW": "0"}
        self.config = {"services": {"backend": {"environment": env},
            "worker": {"environment": worker, "command": ["sh", "-c", "exec celery worker --concurrency=16"]}}}
        self.policy = {"schema_version": 1, "owner": "maintainer", "external_connections": 0,
                       "maintenance_connections": 3, "rollout_surge": {"backend": 0, "worker": 0}}

    def test_default_claim_56(self):
        report = calculate(self.config, self.policy)
        self.assertEqual(report["peak_claim"], 56)
        self.assertEqual(report["errors"], [])

    def test_second_api_replica_and_rollout_overlap_both_fail(self):
        for surge in (False, True):
            config, policy = copy.deepcopy(self.config), copy.deepcopy(self.policy)
            if surge:
                policy["rollout_surge"]["backend"] = 1
            else:
                config["services"]["backend"]["deploy"] = {"replicas": 2}
            report = calculate(config, policy)
            self.assertEqual(report["peak_claim"], 96)
            self.assertTrue(report["errors"])

    def test_reduced_pools_allow_two_replicas_with_declared_external_consumer(self):
        self.config["services"]["backend"]["deploy"] = {"replicas": 2}
        self.config["services"]["backend"]["environment"]["POSTGRES_API_POOL_SIZE"] = "4"
        self.policy["external_connections"] = 8
        report = calculate(self.config, self.policy)
        self.assertEqual(report["peak_claim"], 64)
        self.assertEqual(report["headroom"], 18)
        self.assertEqual(report["errors"], [])

    def test_autoscale_maximum_not_minimum_is_budgeted(self):
        self.config["services"]["worker"]["command"] = "celery worker --autoscale=60,1"
        self.assertTrue(calculate(self.config, self.policy)["errors"])

    def test_unknown_consumer_and_unbounded_pool_fail(self):
        self.config["services"]["new"] = copy.deepcopy(self.config["services"]["worker"])
        with self.assertRaises(ValueError):
            calculate(self.config, self.policy)
        del self.config["services"]["new"]
        self.config["services"]["backend"]["environment"]["POSTGRES_API_POOL_SIZE"] = "0"
        with self.assertRaises(ValueError):
            calculate(self.config, self.policy)

    def test_unsupported_interpreter_is_rejected_before_install(self):
        require_supported_python((3, 11, 15))
        for version in ((3, 10, 0), (3, 12, 0), (3, 13, 0)):
            with self.assertRaises(ValueError):
                require_supported_python(version)


class DocumentationClaimTests(unittest.TestCase):
    def test_expired_ownerless_changed_and_escaping_evidence_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "receipt.json").write_bytes(b"passed")
            claim = {"id": "proof", "owner": "maintainer", "scope": "synthetic only",
                     "limitation": "not production", "status": "verified-local",
                     "reviewed_on": "2026-09-26", "review_by": "2026-12-25",
                     "evidence": [{"path": "receipt.json", "sha256": hashlib.sha256(b"passed").hexdigest()}]}
            self.assertEqual(validate_claims({"claims": [claim]}, root, dt.date(2026, 9, 27)), [])
            for field, value in (("owner", ""), ("review_by", "2026-09-27"),
                                 ("status", "enterprise-guaranteed"),
                                 ("evidence", [{"path": "../escape.json", "sha256": "bad"}]),
                                 ("evidence", [{"path": "receipt.json", "sha256": "bad"}])):
                changed = {**claim, field: value}
                with self.subTest(field=field):
                    self.assertTrue(validate_claims({"claims": [changed]}, root, dt.date(2026, 9, 27)))


if __name__ == "__main__":
    unittest.main()
