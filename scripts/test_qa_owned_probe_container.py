"""Synthetic Docker protocol controls for exact QA resource ownership."""

from __future__ import annotations

import json
import subprocess
import unittest

from qa.owned_probe_container import OWNER_LABEL, OwnedProbeContainer

IMAGE = "sha256:" + "a" * 64
CONTAINER = "c" * 64


class ContainerProtocol:
    def __init__(self, owned):
        self.owned = owned
        self.running = True
        self.calls = []
        self.inspection_error = None
        self.stop_errors = []
        self.overrides = {}
        self.unchanged = False

    def __call__(self, *arguments, timeout=120):
        self.calls.append((arguments, timeout))
        if arguments[:2] == ("docker", "inspect"):
            assert timeout == 10
            if self.inspection_error:
                raise self.inspection_error
            row = {
                "Id": CONTAINER,
                "Image": IMAGE,
                "Name": "/" + self.owned.name,
                "Config": {"Labels": {OWNER_LABEL: self.owned.token}},
                "State": {"Running": self.running},
            }
            row.update(self.overrides)
            return json.dumps([row])
        if arguments[:2] == ("docker", "stop"):
            assert arguments[-1] == CONTAINER
            assert timeout == int(arguments[3]) + 10
            if self.stop_errors:
                raise self.stop_errors.pop(0)
            if not self.unchanged:
                self.running = False
            return CONTAINER
        raise AssertionError(arguments)

    def stops(self):
        return [
            arguments
            for arguments, _ in self.calls
            if arguments[:2] == ("docker", "stop")
        ]


class OwnedProbeContainerTests(unittest.TestCase):
    def setUp(self):
        self.owned = OwnedProbeContainer("synthetic-owned-probe", IMAGE)
        self.command = ContainerProtocol(self.owned)

    def test_lost_run_reply_adopts_only_complete_matching_invocation(self):
        result = self.owned.finish(self.command)
        self.assertEqual(self.owned.identifier, CONTAINER)
        self.assertEqual(result.errors, [])
        self.assertFalse(result.after["Running"])
        self.assertEqual(len(self.command.stops()), 1)

    def test_unrelated_name_image_owner_or_partial_identifier_is_never_stopped(self):
        for override in (
            {"Name": "/another-name"},
            {"Image": "sha256:" + "b" * 64},
            {"Config": {"Labels": {OWNER_LABEL: "another-invocation"}}},
            {"Id": "c" * 12},
        ):
            with self.subTest(override=override):
                owned = OwnedProbeContainer("synthetic-owned-probe", IMAGE)
                command = ContainerProtocol(owned)
                command.overrides = override
                result = owned.finish(command)
                self.assertIsNone(owned.identifier)
                self.assertEqual(command.stops(), [])
                self.assertIsInstance(result.errors[0], ValueError)

    def test_known_returned_id_remains_cleanup_authority_if_inspection_fails(self):
        self.owned.bind_returned_id(CONTAINER)
        original = OSError("synthetic diagnostic failure")
        self.command.inspection_error = original
        result = self.owned.finish(self.command)
        self.assertFalse(self.command.running)
        self.assertIs(result.errors[0], original)
        self.assertIsNone(result.after)
        self.assertEqual(len(self.command.stops()), 2)
        self.assertIn("could not be verified", str(result.errors[-1]))

    def test_absent_unbound_acquisition_never_stops_a_name(self):
        original = subprocess.CalledProcessError(1, "synthetic inspect")
        self.command.inspection_error = original
        result = self.owned.finish(self.command)
        self.assertIs(result.errors[0], original)
        self.assertEqual(self.command.stops(), [])

    def test_verified_identity_with_malformed_state_still_attempts_exact_owned_stop(
        self,
    ):
        self.command.overrides = {"State": None}
        result = self.owned.finish(self.command)
        self.assertEqual(self.owned.identifier, CONTAINER)
        self.assertFalse(self.command.running)
        self.assertIsInstance(result.errors[0], TypeError)
        self.assertEqual(len(self.command.stops()), 2)
        self.assertIsNone(result.after)

    def test_stop_timeout_or_cancel_is_retained_after_bounded_retry_and_readback(self):
        for original in (
            subprocess.TimeoutExpired("synthetic stop", 40),
            KeyboardInterrupt(),
        ):
            with self.subTest(error=type(original).__name__):
                command = ContainerProtocol(self.owned)
                command.stop_errors = [original]
                result = self.owned.finish(command)
                self.assertEqual(result.errors, [original])
                self.assertFalse(result.after["Running"])
                self.assertEqual(len(command.stops()), 2)

    def test_repeated_cancellation_and_unverified_stop_remain_bounded_failures(self):
        first, second = KeyboardInterrupt(), KeyboardInterrupt()
        self.command.stop_errors = [first, second]
        result = self.owned.finish(self.command)
        self.assertEqual(result.errors[:2], [first, second])
        self.assertTrue(result.after["Running"])
        self.assertEqual(len(self.command.stops()), 2)
        self.assertIsInstance(result.errors[-1], RuntimeError)

    def test_exited_owned_container_is_retained_without_a_stop_command(self):
        self.command.running = False
        result = self.owned.finish(self.command)
        self.assertEqual(result.before, result.after)
        self.assertEqual(result.errors, [])
        self.assertEqual(self.command.stops(), [])

    def test_partial_image_or_returned_ids_fail_before_cleanup_authority(self):
        with self.assertRaises(ValueError):
            OwnedProbeContainer("synthetic", "postgres:16")
        with self.assertRaises(ValueError):
            self.owned.bind_returned_id(CONTAINER[:12])
        self.assertIsNone(self.owned.identifier)


if __name__ == "__main__":
    unittest.main()
