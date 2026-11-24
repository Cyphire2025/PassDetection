"""Actual private receipt and command boundaries with synthetic data only."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mcp_activation_database as database
import mcp_activation_identity as identity
from mcp_direct_activate import WRITERS, DirectActivation
from mcp_direct_build import BuildError


class ActivationIoBoundaries(unittest.TestCase):
    def candidates(self, value):
        deployment = object.__new__(DirectActivation)
        with tempfile.TemporaryDirectory() as directory:
            deployment.state = SimpleNamespace(directory=Path(directory))
            deployment.candidate_receipt = "synthetic.private.json"
            (Path(directory) / deployment.candidate_receipt).write_text(
                json.dumps(value), encoding="utf-8"
            )
            with patch.object(identity, "bound_original") as inspect:
                result = deployment.candidates()
            return result, inspect

    def test_normal_candidate_receipt_keeps_every_record_and_identity_check(self):
        rows = {name: {"Id": "synthetic-" + name, "extra": {"preserved": True}} for name in WRITERS}
        actual, inspect = self.candidates(rows)
        self.assertEqual(actual, rows)
        self.assertEqual(inspect.call_count, len(rows))

    def test_non_mapping_receipt_has_existing_bounded_inventory_rejection(self):
        for value in (None, 42, "synthetic-private", list(WRITERS)):
            with self.subTest(value=value):
                with self.assertRaisesRegex(BuildError, "^candidate_service_inventory_changed$"):
                    self.candidates(value)

    def test_incomplete_mapping_keeps_existing_rejection(self):
        with self.assertRaisesRegex(BuildError, "^candidate_service_inventory_changed$"):
            self.candidates({"backend": {"Id": "synthetic"}})

    def execute(self, result, **kwargs):
        deployment = object.__new__(DirectActivation)
        deployment.originals = {"db": {"Id": "synthetic-db"}}
        with (
            patch.object(database, "bound_original", side_effect=lambda row: row),
            patch.object(database.subprocess, "run", return_value=result) as command,
        ):
            output = deployment.database_command(
                ("synthetic-command", "argument"), timeout=30, **kwargs
            )
        return output, command

    def test_command_keeps_scoped_identity_timeout_and_decoded_result(self):
        output, command = self.execute(
            SimpleNamespace(returncode=0, stdout=b"  synthetic-result\n")
        )
        self.assertEqual(output, "synthetic-result")
        self.assertEqual(
            command.call_args.args[0],
            ["docker", "exec", "-i", "synthetic-db", "synthetic-command", "argument"],
        )
        self.assertEqual(command.call_args.kwargs["timeout"], 30)
        self.assertFalse(command.call_args.kwargs["check"])

    def test_binary_file_handles_and_empty_stdout_keep_existing_behavior(self):
        source, target = io.BytesIO(b"synthetic-input"), io.BytesIO()
        output, command = self.execute(
            SimpleNamespace(returncode=0, stdout=None), stdin_file=source, stdout_file=target
        )
        self.assertEqual(output, "")
        self.assertIs(command.call_args.kwargs["stdin"], source)
        self.assertIs(command.call_args.kwargs["stdout"], target)

    def test_command_failure_or_oversize_stdout_rejection_does_not_echo_payload(self):
        for code, raw in ((1, b"synthetic-private"), (0, b"x" * (1024 * 1024 + 1))):
            with self.subTest(code=code, size=len(raw)):
                with self.assertRaisesRegex(BuildError, "^database_command_failed$"):
                    self.execute(SimpleNamespace(returncode=code, stdout=raw))


if __name__ == "__main__":
    unittest.main()
