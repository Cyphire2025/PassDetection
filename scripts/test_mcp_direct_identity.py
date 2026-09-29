"""Docker mount map ordering cannot masquerade as a changed retained container."""
import copy
import unittest
from unittest.mock import patch

from mcp_direct_activate import clean_stop
from mcp_direct_build import BuildError
from mcp_direct_release import bound_original


class ContainerIdentityTests(unittest.TestCase):
    def test_only_explicit_false_and_null_oom_kill_disable_are_equivalent(self):
        before = {"Id": "a" * 64, "Image": "sha256:" + "b" * 64,
                  "Config": {"User": "1001"}, "HostConfig": {"Memory": 123, "OomKillDisable": False}, "Mounts": []}
        for first, last in ((False, None), (None, False), (False, False), (None, None)):
            before["HostConfig"]["OomKillDisable"] = first
            after = copy.deepcopy(before)
            after["HostConfig"]["OomKillDisable"] = last
            retained = copy.deepcopy(before)
            with patch("mcp_direct_release.inspect", return_value=after):
                self.assertIs(bound_original(before), after)
            self.assertEqual(before, retained)
            self.assertIs(after["HostConfig"]["OomKillDisable"], last)

    def test_true_malformed_missing_oom_setting_or_any_other_host_change_is_rejected(self):
        before = {"Id": "a" * 64, "Image": "sha256:" + "b" * 64,
                  "Config": {"User": "1001"}, "HostConfig": {"Memory": 123, "OomKillDisable": False}, "Mounts": []}
        for value in (True, 0, 1, "false", "null", [], {}):
            for side in ("before", "after", "both"):
                original, current = copy.deepcopy(before), copy.deepcopy(before)
                if side in {"before", "both"}:original["HostConfig"]["OomKillDisable"] = value
                if side in {"after", "both"}:current["HostConfig"]["OomKillDisable"] = value
                with self.subTest(value=value, side=side), patch("mcp_direct_release.inspect", return_value=current), self.assertRaisesRegex(BuildError, "configuration_changed"):
                    bound_original(original)
        for mutation in ("missing", "memory", "capability"):
            after = copy.deepcopy(before)
            after["HostConfig"]["OomKillDisable"] = None
            if mutation == "missing":del after["HostConfig"]["OomKillDisable"]
            if mutation == "memory":after["HostConfig"]["Memory"] += 1
            if mutation == "capability":after["HostConfig"]["CapAdd"] = ["SYS_ADMIN"]
            with self.subTest(mutation=mutation), patch("mcp_direct_release.inspect", return_value=after), self.assertRaisesRegex(BuildError, "configuration_changed"):
                bound_original(before)

    def test_only_stopped_node_frontend_accepts_sigterm_status(self):
        row = {"Config": {"Labels": {"com.docker.compose.service": "frontend"},
                          "Cmd": ["node", "server.js"]},
               "State": {"Running": False, "ExitCode": 143, "OOMKilled": False}}
        clean_stop(row)
        for key, value in (("Running", True), ("OOMKilled", True), ("ExitCode", 137)):
            altered = copy.deepcopy(row); altered["State"][key] = value
            with self.assertRaises(BuildError):clean_stop(altered)
        row["Config"]["Labels"]["com.docker.compose.service"] = "backend"
        with self.assertRaises(BuildError):clean_stop(row)

    def test_mount_permutation_preserves_identity_but_field_change_is_rejected(self):
        before = {"Id": "a" * 64, "Image": "sha256:" + "b" * 64,
                  "Config": {"User": "1001"}, "HostConfig": {"Memory": 123},
                  "Mounts": [{"Destination": "/one", "RW": False}, {"Destination": "/two", "RW": True}]}
        after = copy.deepcopy(before)
        after["Mounts"].reverse()
        with patch("mcp_direct_release.inspect", return_value=after):
            self.assertEqual(bound_original(before), after)
            after["Mounts"][0]["RW"] = False
            with self.assertRaisesRegex(BuildError, "configuration_changed"):
                bound_original(before)


if __name__ == "__main__":
    unittest.main()
