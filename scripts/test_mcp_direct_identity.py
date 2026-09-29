"""Docker mount map ordering cannot masquerade as a changed retained container."""
import copy
import unittest
from unittest.mock import patch

from mcp_direct_build import BuildError
from mcp_direct_release import bound_original


class ContainerIdentityTests(unittest.TestCase):
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
