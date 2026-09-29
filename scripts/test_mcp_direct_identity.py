"""Docker mount map ordering cannot masquerade as a changed retained container."""
import copy
import unittest
from unittest.mock import patch

from mcp_direct_build import BuildError
from mcp_direct_release import bound_original
from mcp_direct_activate import clean_stop


class ContainerIdentityTests(unittest.TestCase):
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
