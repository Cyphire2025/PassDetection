"""Worker draining uses synthetic clocks and evidence; never contacts Docker."""

import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from mcp_direct_build import BuildError
from mcp_direct_release import WORKERS, require_idle, wait_for_idle


def evidence():
    containers = {name: {"Config": {"Hostname": name}} for name in WORKERS}
    containers["backend"] = {"Id": "backend", "State": {"Running": True}}
    counts = {
        kind: {f"{prefix}@{name}": 0 for name, prefix in WORKERS.items()}
        for kind in ("active", "reserved", "scheduled")
    }
    return containers, counts


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class WorkerIdleTests(unittest.TestCase):
    def test_busy_work_can_finish_before_release_continues(self):
        clock = Clock()
        containers, counts = evidence()
        def probe(_containers, *, deadline):
            self.assertIs(_containers, containers)
            self.assertEqual(deadline, 1150)
            clock.now += 20  # Count actual probe time, not just backoff.
            if clock.now < 1075:
                raise BuildError("workers_busy_wait_before_build")
            return counts
        with patch("mcp_direct_release.time", clock), \
                patch("mcp_direct_release.require_idle", side_effect=probe) as inspect:
            self.assertIs(wait_for_idle(containers), counts)
        self.assertEqual(inspect.call_count, 4)
        self.assertEqual(clock.sleeps, [5, 5, 5])
        self.assertEqual(clock.now, 1095)

    def test_deadline_caps_total_wait_and_never_starts_another_probe(self):
        clock = Clock()
        def busy(_containers, *, deadline):
            self.assertLess(clock.now, deadline)
            clock.now += min(37, deadline - clock.now)
            raise BuildError("workers_busy_wait_before_build")
        with patch("mcp_direct_release.time", clock), \
                patch("mcp_direct_release.require_idle", side_effect=busy) as inspect, \
                self.assertRaisesRegex(BuildError, "workers_busy_wait_before_build"):
            wait_for_idle({})
        self.assertEqual(inspect.call_count, 4)
        self.assertEqual(clock.sleeps, [5, 5, 5])
        self.assertEqual(clock.now, 1150)

    def test_backoff_is_capped_by_remaining_budget(self):
        clock = Clock()
        def busy(_containers, *, deadline):
            clock.now = deadline - 2
            raise BuildError("workers_busy_wait_before_build")
        with patch("mcp_direct_release.time", clock), \
                patch("mcp_direct_release.require_idle", side_effect=busy) as inspect, \
                self.assertRaises(BuildError):
            wait_for_idle({})
        self.assertEqual(inspect.call_count, 1)
        self.assertEqual(clock.sleeps, [2])
        self.assertEqual(clock.now, 1150)

    def test_late_idle_result_does_not_authorize_release(self):
        clock = Clock()
        def late(_containers, *, deadline):
            clock.now = deadline
            return {}
        with patch("mcp_direct_release.time", clock), \
                patch("mcp_direct_release.require_idle", side_effect=late), \
                self.assertRaisesRegex(BuildError, "workers_busy_wait_before_build"):
            wait_for_idle({})
        self.assertEqual(clock.sleeps, [])

    def test_other_failures_propagate_without_retry_or_sleep(self):
        for failure in (BuildError("worker_idle_evidence_unavailable"),
                        BuildError("direct_build_command_failed"),
                        BuildError("original_container_configuration_changed"),
                        subprocess.TimeoutExpired("docker", 8), RuntimeError("unavailable")):
            clock = Clock()
            with self.subTest(failure=type(failure).__name__), \
                    patch("mcp_direct_release.time", clock), \
                    patch("mcp_direct_release.require_idle", side_effect=failure) as inspect, \
                    self.assertRaises(type(failure)) as raised:
                wait_for_idle({})
            self.assertIs(raised.exception, failure)
            self.assertEqual(inspect.call_count, 1)
            self.assertEqual(clock.sleeps, [])

    def test_idle_requires_all_three_counts_zero_for_every_worker(self):
        containers, counts = evidence()
        for kind in counts:
            changed = copy.deepcopy(counts)
            changed[kind][next(iter(changed[kind]))] = 1
            with self.subTest(kind=kind), \
                    patch("mcp_direct_release.bound_original", return_value=containers["backend"]), \
                    patch("mcp_direct_release.command", return_value="MCP_DIRECT_IDLE=" + json.dumps(changed)), \
                    self.assertRaisesRegex(BuildError, "^workers_busy_wait_before_build$"):
                require_idle(containers)

    def test_missing_nodes_malformed_counts_and_invalid_json_fail_without_retry(self):
        containers, counts = evidence()
        invalid = [None, [], {"active": {}}, {**counts, "active": []}]
        for value in (-1, True, "0"):
            changed = copy.deepcopy(counts)
            changed["active"][next(iter(changed["active"]))] = value
            invalid.append(changed)
        missing = copy.deepcopy(counts)
        missing["scheduled"].pop(next(iter(missing["scheduled"])))
        invalid.append(missing)
        outputs = ["MCP_DIRECT_IDLE=" + json.dumps(value) for value in invalid]
        outputs.extend(["MCP_DIRECT_IDLE={", "no evidence", "MCP_DIRECT_IDLE={}\nMCP_DIRECT_IDLE={}"])
        for output in outputs:
            with self.subTest(output=output[:50]), \
                    patch("mcp_direct_release.bound_original", return_value=containers["backend"]), \
                    patch("mcp_direct_release.command", return_value=output) as command, \
                    patch("mcp_direct_release.time.sleep") as sleep, \
                    self.assertRaisesRegex(BuildError, "^worker_idle_evidence_unavailable$"):
                wait_for_idle(containers)
            command.assert_called_once()
            sleep.assert_not_called()

    def test_container_and_celery_probes_share_remaining_monotonic_budget(self):
        containers, counts = evidence()
        clock = Clock()
        def bind(_container, *, timeout):
            self.assertEqual(timeout, 10)
            clock.now += 3
            return containers["backend"]
        with patch("mcp_direct_release.time", clock), \
                patch("mcp_direct_release.bound_original", side_effect=bind), \
                patch("mcp_direct_release.command", return_value="MCP_DIRECT_IDLE=" + json.dumps(counts)) as command:
            self.assertEqual(require_idle(containers, deadline=1010), counts)
        self.assertEqual(command.call_args.kwargs["timeout"], 7)

    def test_expired_budget_does_not_start_docker_probe(self):
        containers, _ = evidence()
        with patch("mcp_direct_release.time.monotonic", return_value=150), \
                patch("mcp_direct_release.bound_original") as bind, \
                self.assertRaisesRegex(BuildError, "workers_busy_wait_before_build"):
            require_idle(containers, deadline=150)
        bind.assert_not_called()


if __name__ == "__main__":
    unittest.main()
