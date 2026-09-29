"""Capacity and dependency invariants for the explicitly authorized direct lane."""
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from mcp_direct_build import (
    GIB,
    BuildError,
    RetainedBuild,
    admit_builder,
    contract_digest,
    dependency_delta,
)


def locked(name, version, marker=""):
    return f"{name}=={version}{marker} \\\n    --hash=sha256:{'a' * 64}\n    # via reviewed source\n"


class DirectBuildTests(unittest.TestCase):
    def test_backend_builder_has_only_chown_capability_and_repairs_owner_before_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            backend = root / "backend"
            (backend / "contracts").mkdir(parents=True)
            (backend / "contracts/api.openapi.json").write_text('{}')
            previous = root / "previous.lock"
            previous.write_text(locked("same", "1"))
            (backend / "requirements.lock").write_text(locked("same", "1"))
            run = Mock(side_effect=["", "", str(16 * GIB), "a" * 64])
            builder = RetainedBuild(root, root, "e" * 40, run=run)
            builder.create("backend", "sha256:" + "a" * 64, GIB, "/python", [], {})
            create_args = run.call_args.args
            self.assertEqual(create_args[create_args.index("--cap-drop") + 1], "ALL")
            self.assertEqual(create_args[create_args.index("--cap-add") + 1], "CHOWN")
            builder.create = Mock(return_value="a" * 64)
            builder.execute = Mock(return_value={"container_id": "a" * 64})
            builder.run = Mock(return_value="sha256:" + "b" * 64)
            builder.backend("sha256:" + "a" * 64, previous)
            code = builder.create.call_args.args[4][1]
            final_call = ast.parse(code).body[-1].value
            self.assertEqual(ast.literal_eval(final_call.args[0]), ["/bin/chown", "-R", "1001:1001", "/app"])
            self.assertEqual(builder.run.call_args.args[:2], ("docker", "commit"))

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
