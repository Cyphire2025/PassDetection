"""Release mismatches must fail before an operator activates containers."""

import copy
import unittest

from release_current import CurrentRelease
from release_manifest import load_release_manifest, verify_rendered_release, verify_source_defaults
from release_traveller_whatsapp import ReleaseError, validate_worker_probe


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_release_manifest()
        self.config = {"services": {
            name: {"environment": {"EXPECTED_DATABASE_SCHEMA_REVISION": self.manifest["schema_revision"]},
                   "command": f"celery worker --hostname={prefix}@%h"}
            for name, prefix in self.manifest["worker_nodes"].items()
        }}
        for name in ("email-beat", "backend"):
            self.config["services"][name] = {
                "environment": {"EXPECTED_DATABASE_SCHEMA_REVISION": self.manifest["schema_revision"]}
            }

    def test_current_source_and_rendered_configuration_agree(self):
        verify_source_defaults()
        verify_rendered_release(self.config, self.manifest)

    def test_actual_stale_environment_is_rejected_without_replacement(self):
        for name in self.config["services"]:
            config = copy.deepcopy(self.config)
            config["services"][name]["environment"]["EXPECTED_DATABASE_SCHEMA_REVISION"] = "0093_phone_welcome"
            with self.assertRaisesRegex(ValueError, "configured schema"):
                verify_rendered_release(config, self.manifest)

    def test_missing_worker_or_wrong_node_is_rejected(self):
        config = copy.deepcopy(self.config)
        del config["services"]["ecr-worker"]
        with self.assertRaisesRegex(ValueError, "Missing release service"):
            verify_rendered_release(config, self.manifest)
        self.config["services"]["ecr-worker"]["command"] = "celery worker --hostname=general@%h"
        with self.assertRaisesRegex(ValueError, "worker node prefix"):
            verify_rendered_release(self.config, self.manifest)

    def test_current_release_requires_all_eight_workers(self):
        release = CurrentRelease("a" * 40)
        self.assertEqual(len(release.node_prefixes), 8)
        self.assertIn("ecr-worker", release.activated_services)
        nodes = {f"{prefix}@host" for prefix in release.node_prefixes.values()}
        payload = {"ping": {node: {"ok": "pong"} for node in nodes}}
        validate_worker_probe(payload, nodes, idle=False, expected_count=8)
        del payload["ping"]["ecr@host"]
        with self.assertRaises(ReleaseError):
            validate_worker_probe(payload, nodes, idle=False, expected_count=8)


if __name__ == "__main__":
    unittest.main()
