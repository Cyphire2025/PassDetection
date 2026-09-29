"""Ownership repair never substitutes runtime identity or bypasses host capacity."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mcp_direct_build import GIB, BuildError
from mcp_direct_repair import VALIDATE, repair_backend_image


class RepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.source = self.directory / "source"
        self.source.mkdir()
        self.state = Mock(
            directory=self.directory, source=self.source, revision="e" * 40
        )
        self.base_id = "sha256:" + "a" * 64
        self.fixed_id = "sha256:" + "b" * 64
        self.contract = "c" * 64
        self.images = {
            "revision": self.state.revision,
            "backend": {
                "image_id": self.base_id,
                "base_image_id": "sha256:" + "d" * 64,
                "verified_api_contract_sha256": self.contract,
            },
            "frontend": {"image_id": "sha256:" + "f" * 64},
        }
        self.receipt = self.directory / "images.json"
        self.receipt.write_text(json.dumps(self.images))
        self.original_receipt = self.receipt.read_bytes()
        self.config = {
            "User": "1001:1001",
            "WorkingDir": "/app",
            "Entrypoint": [],
            "Cmd": ["gunicorn", "--config", "gunicorn.conf.py", "app.main:app"],
            "Env": ["APP_REVISION=" + self.state.revision],
            "Labels": {"org.opencontainers.image.revision": self.state.revision},
        }
        self.client = Mock()
        self.client.request.return_value = {"Id": self.fixed_id}
        self.calls, self.identifiers = [], []
        self.host_bytes, self.used_bytes = 16 * GIB, 10 * GIB
        self.exit_code = "0"
        self.fixed_config_changed = False
        self.addCleanup(patch.stopall)
        patch(
            "mcp_direct_repair._validation_payload",
            return_value=("encoded-source", self.contract),
        ).start()

    def run_command(self, *args, **kwargs):
        self.calls.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            config = copy.deepcopy(self.config)
            if args[-1] == self.fixed_id and self.fixed_config_changed:
                config["User"] = "0:0"
            return json.dumps([{"Id": args[-1], "Config": config}])
        if args[:3] == ("docker", "ps", "-a"):
            return ""
        if args[:3] == ("docker", "ps", "-q"):
            return "d" * 64
        if args[:3] == ("docker", "inspect", "--format"):
            return json.dumps({"Running": False, "OOMKilled": False})
        if args[:2] == ("docker", "inspect"):
            return json.dumps([{"HostConfig": {"Memory": self.used_bytes}}])
        if args[:2] == ("docker", "info"):
            return str(self.host_bytes)
        if args[:2] == ("docker", "create"):
            identifier = f"{len(self.identifiers) + 1:064x}"
            self.identifiers.append(identifier)
            return identifier
        if args[:2] == ("docker", "start"):
            return args[-1]
        if args[:2] == ("docker", "wait"):
            return self.exit_code if args[-1] == f"{2:064x}" else "0"
        if args[:2] == ("docker", "logs"):
            return (
                "MCP_REPAIR_RUNTIME_VERIFIED"
                if args[-1] == f"{2:064x}" and self.exit_code == "0"
                else ""
            )
        raise AssertionError(args)

    def repair(self):
        return repair_backend_image(
            self.state,
            self.images,
            "ownership-v1",
            run=self.run_command,
            client=self.client,
        )

    def test_only_chown_then_uid1001_validation_preserves_image_config_and_receipts(
        self,
    ):
        before = copy.deepcopy(self.images)
        result = self.repair()
        creates = [call for call in self.calls if call[:2] == ("docker", "create")]
        first, second = creates
        self.assertEqual(first[-4:], (self.base_id, "-R", "1001:1001", "/app"))
        self.assertEqual(first[first.index("--entrypoint") + 1], "/bin/chown")
        self.assertEqual(first[first.index("--cap-add") + 1], "CHOWN")
        self.assertEqual(first[first.index("--memory") + 1], str(GIB // 4))
        self.assertEqual(second[second.index("--user") + 1], "1001:1001")
        self.assertEqual(second[second.index("--memory") + 1], str(GIB))
        self.assertIn("--read-only", second)
        for call in creates:
            self.assertEqual(call[call.index("--network") + 1], "none")
            self.assertNotIn("--volume", call)
            self.assertNotIn("--rm", call)
        self.assertEqual(self.client.request.call_args.args[2], self.config)
        self.assertEqual(result["backend"]["image_id"], self.fixed_id)
        self.assertEqual(result["frontend"], self.images["frontend"])
        self.assertEqual(self.images, before)
        self.assertEqual(self.receipt.read_bytes(), self.original_receipt)
        self.assertTrue((self.directory / "images-ownership-v1.json").is_file())

    def test_every_start_has_fresh_whole_host_capacity_admission(self):
        self.repair()
        starts = [
            index
            for index, call in enumerate(self.calls)
            if call[:2] == ("docker", "start")
        ]
        self.assertEqual(len(starts), 2)
        for index in starts:
            self.assertEqual(self.calls[index - 1][:2], ("docker", "info"))
            self.assertEqual(self.calls[index - 2][:2], ("docker", "inspect"))
            self.assertEqual(self.calls[index - 3][:3], ("docker", "ps", "-q"))

    def test_host_reserve_failure_prevents_any_create_or_start(self):
        self.host_bytes = 12 * GIB
        with self.assertRaisesRegex(BuildError, "host_reserve"):
            self.repair()
        self.assertFalse(
            any(
                call[:2] in {("docker", "create"), ("docker", "start")}
                for call in self.calls
            )
        )

    def test_failed_uid_validation_retains_helpers_but_no_success_receipt(self):
        self.exit_code = "2"
        with self.assertRaisesRegex(BuildError, "builder_failed"):
            self.repair()
        self.assertEqual(len(self.identifiers), 2)
        self.assertFalse((self.directory / "images-ownership-v1.json").exists())
        self.assertFalse(
            any(
                call[:2] in {("docker", "rm"), ("docker", "rmi"), ("docker", "stop")}
                for call in self.calls
            )
        )
        self.assertEqual(self.receipt.read_bytes(), self.original_receipt)

    def test_changed_runtime_config_stops_before_validation(self):
        self.fixed_config_changed = True
        with self.assertRaisesRegex(BuildError, "runtime_image_config_changed"):
            self.repair()
        self.assertEqual(len(self.identifiers), 1)

    def test_changed_source_receipt_or_image_user_is_rejected_before_create(self):
        self.images["backend"]["image_id"] = self.fixed_id
        with self.assertRaisesRegex(BuildError, "receipt_changed"):
            self.repair()
        self.images["backend"]["image_id"] = self.base_id
        self.config["User"] = "0:0"
        with self.assertRaisesRegex(BuildError, "image_binding_changed"):
            self.repair()
        self.assertEqual(self.identifiers, [])

    def test_existing_repair_receipt_is_never_overwritten(self):
        path = self.directory / "images-ownership-v1.json"
        path.write_text("retained")
        with self.assertRaisesRegex(BuildError, "already_retained"):
            self.repair()
        self.assertEqual(path.read_text(), "retained")
        self.assertEqual(self.identifiers, [])

    def test_validation_code_rejects_root_before_reading_application_sources(self):
        with (
            patch("os.getuid", return_value=0, create=True),
            patch("os.getgid", return_value=0, create=True),
            patch("builtins.print") as output,
            self.assertRaises(SystemExit) as error,
        ):
            exec(compile(VALIDATE, "repair-uid-validation", "exec"), {})  # noqa: S102 - run the fixed code-owned validator
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(output.call_args_list[0].args, ("MCP_REPAIR_RUNTIME_FAILED",))
        self.assertNotIn("AssertionError(", str(output.call_args_list))


if __name__ == "__main__":
    unittest.main()
