"""Capacity and dependency invariants for the explicitly authorized direct lane."""
import unittest

from mcp_direct_build import BuildError, GIB, admit_builder, contract_digest, dependency_delta


def locked(name, version, marker=""):
    return f"{name}=={version}{marker} \\\n    --hash=sha256:{'a' * 64}\n    # via reviewed source\n"


class DirectBuildTests(unittest.TestCase):
    def test_contract_newlines_do_not_hide_or_invent_semantic_drift(self):
        self.assertEqual(contract_digest(b'{\n "version":"1"\n}\n'), contract_digest(b'{\r\n "version":"1"\r\n}\r\n'))
        self.assertNotEqual(contract_digest(b'{"version":"1"}'), contract_digest(b'{"version":"2"}'))

    def test_delta_retains_markers_hashes_and_only_new_or_changed_versions(self):
        old = locked("same", "1") + locked("changed", "1")
        new = locked("same", "1") + locked("changed", "2") + locked("added", "3", "; sys_platform == 'linux'")
        delta = dependency_delta(old, new)
        self.assertNotIn("same==", delta)
        self.assertIn(locked("changed", "2"), delta)
        self.assertIn(locked("added", "3", "; sys_platform == 'linux'"), delta)

    def test_dependency_removal_or_unhashed_package_is_rejected(self):
        for before, after in ((locked("a", "1"), locked("b", "1")),
                              (locked("a", "1"), "a==2\n"), ("", locked("a", "1"))):
            with self.subTest(after=after), self.assertRaises(BuildError):
                dependency_delta(before, after)

    def test_running_caps_include_unrelated_services_and_fixed_host_reserve(self):
        running = [{"HostConfig": {"Memory": 10 * GIB}}, {"HostConfig": {"Memory": GIB}}]
        admit_builder(running, 16 * GIB, 3 * GIB)
        with self.assertRaisesRegex(BuildError, "builder_exceeds_host_reserve"):
            admit_builder(running, 16 * GIB - 1, 3 * GIB)

    def test_unbounded_or_invalid_caps_fail_before_creation(self):
        for value in (0, -1, None, True):
            with self.subTest(value=value), self.assertRaises(BuildError):
                admit_builder([{"HostConfig": {"Memory": value}}], 16 * GIB, GIB)
        with self.assertRaises(BuildError):
            admit_builder([], 16 * GIB, 4 * GIB)


if __name__ == "__main__":
    unittest.main()
