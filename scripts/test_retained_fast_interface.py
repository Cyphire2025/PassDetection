"""Code-only FastBuild substitutability with no Docker or operational credentials."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mcp_direct_build import BuildError, RetainedBuild
from retained_release_fast import FastBuild

IMAGE = "sha256:" + "a" * 64
LOCK = b"synthetic==1 \\\n    --hash=sha256:" + b"b" * 64 + b"\n"


def build_through_base(builder: RetainedBuild, previous_lock: Path) -> dict:
    return builder.backend(IMAGE, previous_lock)


class RetainedFastInterfaceTests(unittest.TestCase):
    def builder(self, root):
        (root / "backend/contracts").mkdir(parents=True)
        (root / "backend/contracts/api.openapi.json").write_text("{}", encoding="utf-8")
        (root / "backend/requirements.lock").write_bytes(LOCK)
        builder = FastBuild(root, root, "c" * 40, run=Mock())
        builder.create = Mock(return_value="d" * 64)
        builder.execute = Mock(return_value={"exit_code": 0})
        builder.commit_runtime = Mock(return_value="sha256:" + "e" * 64)
        return builder

    def test_legacy_one_argument_code_only_call_still_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            builder = self.builder(root)
            result = builder.backend(IMAGE)
            self.assertEqual(result["base_image_id"], IMAGE)
            builder.create.assert_called_once()

    def test_base_typed_unchanged_lock_call_uses_same_fast_builder_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            builder = self.builder(root)
            previous = root / "previous.lock"
            previous.write_bytes(LOCK)
            with patch("retained_release_fast.uuid.uuid4", return_value=Mock(hex="f" * 32)):
                expected = builder.backend(IMAGE)
                expected_create = builder.create.call_args
                expected_copy = builder.run.call_args
                builder.create.reset_mock()
                builder.run.reset_mock()
                actual = build_through_base(builder, previous)
            self.assertEqual(actual, expected)
            self.assertEqual(builder.create.call_args, expected_create)
            self.assertEqual(builder.run.call_args, expected_copy)
            builder.execute.assert_called_with("d" * 64, "backend", 1024**3)
            builder.commit_runtime.assert_called_with("d" * 64, "backend")
            self.assertFalse((root / "backend-delta.lock").exists())

    def test_same_lock_with_checkout_line_endings_remains_code_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            builder = self.builder(root)
            previous = root / "previous.lock"
            previous.write_bytes(LOCK.replace(b"\n", b"\r\n"))
            self.assertEqual(build_through_base(builder, previous)["base_image_id"], IMAGE)
            builder.create.assert_called_once()

    def test_changed_dependency_lock_is_rejected_before_any_builder_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            builder = self.builder(root)
            previous = root / "previous.lock"
            previous.write_bytes(LOCK.replace(b"synthetic==1", b"synthetic==2"))
            with self.assertRaisesRegex(BuildError, "^fast_build_requires_unchanged_dependency_lock$"):
                build_through_base(builder, previous)
            for method in (builder.create, builder.run, builder.execute, builder.commit_runtime):
                method.assert_not_called()

    def test_unavailable_dependency_evidence_fails_closed_before_building(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            builder = self.builder(root)
            with self.assertRaisesRegex(BuildError, "^fast_build_dependency_lock_unavailable$"):
                build_through_base(builder, root / "missing.lock")
            builder.create.assert_not_called()

    def test_subclass_super_keeps_override_dispatch_and_original_one_argument_call(self):
        class DerivedBuild(FastBuild):
            def backend(self, base_image, previous_lock=None):
                return {**super().backend(base_image, previous_lock), "derived": True}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            template = self.builder(root)
            builder = DerivedBuild(root, root, "c" * 40, run=template.run)
            builder.create = template.create
            builder.execute = template.execute
            builder.commit_runtime = template.commit_runtime
            self.assertTrue(builder.backend(IMAGE)["derived"])
            self.assertEqual(DerivedBuild.__mro__[:3], (DerivedBuild, FastBuild, RetainedBuild))


if __name__ == "__main__":
    unittest.main()
