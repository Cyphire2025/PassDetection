"""Actual shared release methods, synthetic decoded Docker data and no services."""

import hashlib
import json
import unittest
from unittest.mock import Mock, patch

import release_retained_update as facade
import retained_release_host as host
import retained_release_runtime as runtime

REVISION = "a" * 40


class RetainedJsonBoundaries(unittest.TestCase):
    def test_normal_inventory_preserves_original_objects_and_command_scope(self):
        rows = [{"Id": "synthetic-one", "extra": {"preserved": True}}, {"Id": "synthetic-two"}]
        release = object.__new__(facade.RetainedUpdate)
        with patch.object(host, "command", side_effect=["one two", json.dumps(rows)]) as command:
            self.assertEqual(release.rows(all=True), rows)
        self.assertEqual(command.call_args_list[0].args, ("docker", "ps", "-aq", "--no-trunc"))
        self.assertEqual(command.call_args_list[1].args, ("docker", "inspect", "one", "two"))
        self.assertEqual(command.call_args_list[1].kwargs, {"timeout": 120})

    def test_empty_inventory_does_not_inspect_an_unbounded_default_selection(self):
        release = object.__new__(facade.RetainedUpdate)
        with patch.object(host, "command", return_value="") as command:
            self.assertEqual(release.rows(), [])
        command.assert_called_once_with("docker", "ps", "-q", "--no-trunc")

    def test_non_string_service_identity_uses_existing_bounded_rejection(self):
        for name in (None, ["synthetic-private"]):
            with self.subTest(name=name):
                rows = [{"Config": {"Labels": {"com.docker.compose.service": name}}}]
                with self.assertRaisesRegex(ValueError, "^ambiguous_running_service_inventory$"):
                    facade.select_live(rows)

    def test_non_object_inventory_rows_fail_with_bounded_reason(self):
        for value in (None, {}, "synthetic-private", 42, ["synthetic-private"]):
            with self.subTest(value=value):
                release = object.__new__(facade.RetainedUpdate)
                with patch.object(host, "command", side_effect=["one", json.dumps(value)]):
                    with self.assertRaisesRegex(ValueError, "^invalid_docker_inventory$"):
                        release.rows()

    def proof(self, asset):
        release = object.__new__(facade.RetainedUpdate)
        release.wait_health = Mock()
        release.retention = Mock()
        rows = {
            "backend": {"Id": "synthetic-backend"},
            "frontend": {
                "Id": "synthetic-frontend",
                "Config": {"Env": ["NEXT_PUBLIC_APP_REVISION=" + REVISION]},
            },
        }

        def command(*args):
            return json.dumps(asset) if args[-1] == REVISION else ""

        with (
            patch.object(runtime, "command", side_effect=command),
            patch.object(runtime, "bound_original", side_effect=lambda row: row),
            patch.object(runtime, "wait_full_readiness"),
            patch.object(
                runtime.subprocess, "check_output", return_value=b"synthetic-asset"
            ) as fetch,
        ):
            release.proof(rows, REVISION, public=True)
        release.retention.assert_called_once_with()
        return fetch

    def test_normal_asset_proof_keeps_existing_revision_path_digest_gate(self):
        asset = {
            "path": "/_next/static/synthetic.js",
            "sha256": hashlib.sha256(b"synthetic-asset").hexdigest(),
        }
        fetch = self.proof(asset)
        self.assertEqual(fetch.call_args.args[0][-1], facade.ORIGIN + asset["path"])
        self.assertEqual(fetch.call_args.kwargs, {"timeout": 40})

    def test_non_object_asset_json_fails_with_existing_bounded_reason(self):
        for value in (None, [], "synthetic-private", 42):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "^invalid_frontend_revision_asset$"):
                    self.proof(value)


if __name__ == "__main__":
    unittest.main()
