"""New image bytes, compiler/header exposure and unsafe allocation fail closed."""
from __future__ import annotations

import copy
import ctypes
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from qa import gcc_runtime_policy as gcc


class GccRuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / gcc.LIBRARY.lstrip("/")
        self.library.parent.mkdir(parents=True)
        self.library.write_bytes(b"reviewed library")
        self.digest = hashlib.sha256(self.library.read_bytes()).hexdigest()
        self.manifest = {"schema_version": 1, "packages": [
            {"name": name, "version": gcc.VERSION,
             "paths": {gcc.LIBRARY: {"type": "file", "sha256": self.digest}}}
            for name in gcc.PACKAGES]}
        self.installed = "\n".join(f"{name}\t{gcc.VERSION}\tinstall ok installed" for name in gcc.PACKAGES)
        self.files = {name: gcc.LIBRARY + "\n" for name in gcc.PACKAGES}
        self.hash_patch = patch.object(gcc, "LIBRARY_SHA256", self.digest)
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)

    def verify(self, installed=None, manifest=None, files=None):
        return gcc.verify_package_contents(manifest or self.manifest,
                                          self.installed if installed is None else installed,
                                          self.files if files is None else files, self.root)

    def test_reviewed_versions_and_actual_bytes_pass(self):
        self.assertEqual(self.verify(), 4)

    def test_different_hash_or_missing_runtime_library_is_rejected(self):
        self.library.write_bytes(b"changed library")
        with self.assertRaisesRegex(RuntimeError, "content changed"):
            self.verify()
        self.library.unlink()
        with self.assertRaisesRegex(RuntimeError, "content changed"):
            self.verify()

    def test_changed_version_partial_install_missing_or_duplicate_package_is_rejected(self):
        rows = self.installed.splitlines()
        for installed in (self.installed.replace(gcc.VERSION, "14.2.0-20", 1),
                          self.installed.replace("install ok installed", "unpack ok unpacked", 1),
                          "\n".join(rows[1:]), "\n".join([*rows, rows[0]])):
            with self.subTest(installed=installed), self.assertRaises(RuntimeError):
                self.verify(installed=installed)

    def test_new_package_owned_component_or_manifest_version_is_rejected(self):
        files = dict(self.files)
        files[gcc.PACKAGES[0]] += "/usr/include/c++/14/ext/pb_ds/priority_queue.hpp\n"
        with self.assertRaisesRegex(RuntimeError, "unreviewed runtime files"):
            self.verify(files=files)
        manifest = copy.deepcopy(self.manifest)
        manifest["packages"][0]["version"] = "other"
        with self.assertRaisesRegex(RuntimeError, "manifest version"):
            self.verify(manifest=manifest)

    def test_removed_packaging_metadata_is_optional_but_changed_existing_bytes_are_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        filename = "/usr/share/lintian/overrides/libgcc-s1"
        manifest["packages"][0]["paths"][filename] = {"type": "file", "sha256": "0" * 64}
        self.assertEqual(self.verify(manifest=manifest), 4)
        metadata = self.root / filename.lstrip("/")
        metadata.parent.mkdir(parents=True)
        metadata.write_bytes(b"changed metadata")
        with self.assertRaisesRegex(RuntimeError, "content changed"):
            self.verify(manifest=manifest)

    def test_compiler_package_and_copied_affected_header_are_rejected(self):
        gcc.reject_development_components("gcc-14-base\tinstall ok installed", self.root)
        for name in ("gcc", "gcc-14", "g++-14", "libstdc++-14-dev", "gcc-14-x86-64-linux-gnu"):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "reintroduced"):
                gcc.reject_development_components(name + "\tinstall ok installed", self.root)
        header = self.root / "opt/custom/pb_ds/priority_queue.hpp"
        header.parent.mkdir(parents=True)
        header.write_text("template")
        with self.assertRaisesRegex(RuntimeError, "PBDS header"):
            gcc.reject_development_components("gcc-14-base\tinstall ok installed", self.root)

    def test_copied_compiler_outside_dpkg_is_rejected(self):
        binary = self.root / "usr/local/bin/g++"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"compiler")
        with self.assertRaisesRegex(RuntimeError, "compiler present"):
            gcc.reject_development_components("gcc-14-base\tinstall ok installed", self.root)

    def make_cpp(self, boundary_result=None):
        cpp = Mock()
        cpp._ZSt15get_new_handlerv.return_value = None
        for name, _delete in gcc.OPERATORS:
            getattr(cpp, name).side_effect = lambda size, _align, _tag: 4096 if size == 128 else boundary_result
        return cpp

    def test_actual_both_operator_paths_and_all_boundary_arguments_are_checked(self):
        cpp = self.make_cpp()
        tag = ctypes.c_char()
        with patch.object(gcc.ctypes, "c_char") as char:
            char.in_dll.return_value = tag
            self.assertEqual(gcc.aligned_new_boundaries(cpp), 18)
        for name, delete in gcc.OPERATORS:
            calls = getattr(cpp, name).call_args_list
            self.assertEqual([call.args[:2] for call in calls], [(128, 32), *gcc.BOUNDARIES])
            getattr(cpp, delete).assert_called_once_with(4096, 32)

    def test_undersized_allocation_is_freed_and_rejected(self):
        cpp = self.make_cpp(boundary_result=8192)
        tag = ctypes.c_char()
        with patch.object(gcc.ctypes, "c_char") as char:
            char.in_dll.return_value = tag
            with self.assertRaisesRegex(RuntimeError, "unsafe undersized"):
                gcc.aligned_new_boundaries(cpp)
        getattr(cpp, gcc.OPERATORS[0][1]).assert_called_with(8192, 32)

    def test_failed_or_misaligned_control_and_replaced_new_handler_are_rejected(self):
        for control in (None, 4097):
            cpp = self.make_cpp()
            getattr(cpp, gcc.OPERATORS[0][0]).side_effect = None
            getattr(cpp, gcc.OPERATORS[0][0]).return_value = control
            tag = ctypes.c_char()
            with patch.object(gcc.ctypes, "c_char") as char:
                char.in_dll.return_value = tag
                with self.assertRaisesRegex(RuntimeError, "control"):
                    gcc.aligned_new_boundaries(cpp)
        cpp = self.make_cpp()
        cpp._ZSt15get_new_handlerv.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "new-handler"):
            gcc.aligned_new_boundaries(cpp)


if __name__ == "__main__":
    unittest.main()
