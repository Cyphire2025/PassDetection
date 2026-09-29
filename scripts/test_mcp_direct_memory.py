"""Retained historic OOM counters are acceptable; any new event fails cutover."""

import copy
import unittest
from unittest.mock import patch

from mcp_direct_build import BuildError
from mcp_direct_memory import capture, compare, require_zero


def snapshot():
    return {
        "containers": {
            "nginx": {
                "id": "a" * 64,
                "started_at": "earlier",
                "restarts": 0,
                "oom_killed": True,
                "events": {
                    "oom": 151,
                    "oom_kill": 3,
                    "oom_group_kill": 0,
                    "max": 44342,
                },
            }
        }
    }


class DirectMemoryTests(unittest.TestCase):
    def test_static_binding_error_is_preserved_instead_of_masked_as_missing_cgroup(self):
        failure = BuildError("original_container_configuration_changed")
        with (
            patch("mcp_direct_memory.sys.platform", "linux"),
            patch.dict("os.environ", {}, clear=True),
            patch("mcp_direct_memory.command", return_value="unix:///var/run/docker.sock"),
            self.assertRaises(BuildError) as raised,
        ):
            def inspect(_row):
                raise failure
            capture({"backend": {}}, inspect=inspect)
        self.assertIs(raised.exception, failure)

    def test_unchanged_historical_events_are_preserved(self):
        first, last = snapshot(), snapshot()
        last["containers"]["nginx"]["events"]["max"] += 1
        compare(first, last)

    def test_increment_missing_counter_counter_reset_identity_and_restart_fail(self):
        for mutation in (
            "oom",
            "oom_kill",
            "oom_group_kill",
            "missing",
            "reset",
            "id",
            "started_at",
            "restarts",
        ):
            first, last = snapshot(), snapshot()
            row = last["containers"]["nginx"]
            if mutation in {"oom", "oom_kill", "oom_group_kill"}:
                row["events"][mutation] += 1
            elif mutation == "missing":
                del row["events"]["oom"]
            elif mutation == "reset":
                row["events"]["oom"] = 0
            else:
                row[mutation] = "changed"
            with self.subTest(mutation=mutation), self.assertRaises(BuildError):
                compare(first, last)

    def test_new_container_requires_zero_events_and_no_restart_or_flag(self):
        current = snapshot()
        row = current["containers"]["nginx"]
        row["oom_killed"] = False
        row["events"] = {"oom": 0, "oom_kill": 0}
        require_zero(current)
        for field in ("oom", "oom_kill", "restarts", "oom_killed"):
            changed = copy.deepcopy(current)
            candidate = changed["containers"]["nginx"]
            if field in candidate["events"]:
                candidate["events"][field] = 1
            else:
                candidate[field] = 1
            with self.subTest(field=field), self.assertRaises(BuildError):
                require_zero(changed)

    def test_nonlocal_daemon_or_host_evidence_is_unavailable_without_raw_details(self):
        with (
            patch("mcp_direct_memory.sys.platform", "linux"),
            patch("mcp_direct_memory.command", return_value="tcp://remote"),
            self.assertRaisesRegex(BuildError, "bound_cgroup_evidence_unavailable"),
        ):
            capture({"nginx": {}}, inspect=lambda row: row)


if __name__ == "__main__":
    unittest.main()
