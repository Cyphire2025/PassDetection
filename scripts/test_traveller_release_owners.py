"""Shared release compatibility, override dispatch and networkless CLI checks."""

from __future__ import annotations

import inspect
import json
import os
import pickle
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints
from unittest.mock import patch

import release_document_resources as qualification
import release_traveller_whatsapp as facade
from traveller_release_host import _ReleaseHost
from traveller_release_preparation import _ReleasePreparation
from traveller_release_readiness import _ReleaseReadiness


class ProbeRelease(facade.Release):
    def __init__(self, root):
        super().__init__("a" * 40, root)
        self.events = []
        self.compose = ["docker", "compose", "-p", "synthetic"]
        self.refs = {name: "worker-image" for name in self.workers}
        self.refs.update(backend="backend-image", frontend="frontend-image")

    def say(self, phase):
        self.phase = phase

    def preflight(self):
        self.events.append("preflight")
        return {
            "name": "synthetic",
            "services": {name: {"image": ref} for name, ref in self.refs.items()},
        }

    def config_fingerprint(self, config):
        return "synthetic-fingerprint"

    def prepare_recovery(self, config):
        self.events.append("recovery-hook")

    def prepare_images(self, config, refs):
        self.events.append("prepare-override")
        return super().prepare_images(config, refs)

    def dc(self, *args, **kwargs):
        if args == ("config", "--images"):
            return "\n".join(self.refs.values())
        self.events.append(("dc", args, kwargs))
        return ""

    def verify_image(self, reference, *, backend):
        self.events.append(("image", reference, backend))
        return (
            "sha256:"
            + {"worker-image": "1", "backend-image": "2", "frontend-image": "3"}[reference] * 64
        )

    def write_private(self, path, data, *, exclusive=False):
        self.saved_manifest = json.loads(data)

    def container(self, service):
        self.events.append(("container-override", service))
        return super().container(service)

    def run(self, *args, **kwargs):
        self.events.append(("run", args, kwargs))
        if args[:2] == ("docker", "ps"):
            return "synthetic-container"
        if args[:2] == ("docker", "inspect"):
            return json.dumps(
                [
                    {
                        "State": {"Running": True},
                        "Config": {
                            "Labels": {
                                facade.SERVICE_LABEL: "backend",
                                facade.PROJECT_LABEL: "synthetic",
                            }
                        },
                    }
                ]
            )
        raise AssertionError("Only synthetic inspected container paths are allowed")


class ReleaseOwnerTests(unittest.TestCase):
    def test_qualification_binds_each_real_shared_operator_owner_and_rejects_missing_source(self):
        expected = {
            "scripts/release_traveller_whatsapp.py",
            "scripts/traveller_release_contract.py",
            "scripts/traveller_release_host.py",
            "scripts/traveller_release_readiness.py",
            "scripts/traveller_release_preparation.py",
            "scripts/traveller_release_lifecycle.py",
        }
        self.assertTrue(expected <= set(qualification.QUALIFIED_SOURCES))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in qualification.QUALIFIED_SOURCES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic qualification source\n", encoding="utf-8")
            initial = qualification.qualified_source_hashes(root)
            changed = root / "scripts/traveller_release_host.py"
            changed.write_text("synthetic changed host owner\n", encoding="utf-8")
            updated = qualification.qualified_source_hashes(root)
            self.assertEqual(
                {name for name in initial if initial[name] != updated[name]},
                {
                    "scripts/traveller_release_host.py",
                },
            )
            changed.unlink()
            with self.assertRaises(FileNotFoundError):
                qualification.qualified_source_hashes(root)

    def test_private_bases_have_no_runtime_fake_fields_or_constructors(self):
        self.assertEqual(
            facade.Release.__mro__,
            (
                facade.Release,
                _ReleasePreparation,
                _ReleaseReadiness,
                _ReleaseHost,
                object,
            ),
        )
        for base in (_ReleasePreparation, _ReleaseReadiness, _ReleaseHost):
            self.assertNotIn("__init__", vars(base))
            self.assertNotIn("__slots__", vars(base))
            self.assertNotIn("__getattr__", vars(base))
            self.assertNotIn("root", vars(base))
            self.assertEqual(get_type_hints(base), {})
        self.assertEqual(get_type_hints(facade.Release), {})

    def test_static_descriptor_and_legacy_pickle_names_remain_usable(self):
        descriptor = inspect.getattr_static(facade.Release, "sync_directory")
        self.assertIsInstance(descriptor, staticmethod)
        function = facade.Release.sync_directory
        self.assertEqual(function.__qualname__, "Release.sync_directory")
        self.assertEqual(function.__module__, "release_traveller_whatsapp")
        self.assertIs(pickle.loads(pickle.dumps(function)), function)
        self.assertIs(pickle.loads(pickle.dumps(facade.Release)), facade.Release)
        self.assertIs(pickle.loads(pickle.dumps(facade.ReleaseError)), facade.ReleaseError)
        self.assertTrue(get_type_hints(function))

    def test_real_subclass_super_and_virtual_recovery_hook_dispatch_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            release = ProbeRelease(Path(directory))
            release.prepare()
            self.assertLess(
                release.events.index("recovery-hook"), release.events.index("prepare-override")
            )
            self.assertEqual(release.events[0], "preflight")
            self.assertEqual(release.events[-1], "preflight")
            build = next(row for row in release.events if isinstance(row, tuple) and row[0] == "dc")
            self.assertEqual(
                build[1],
                (
                    "build",
                    "--build-arg",
                    "APP_REVISION=" + "a" * 40,
                    "backend",
                    "worker",
                    "frontend",
                ),
            )
            self.assertEqual(build[2], {"timeout": 7200, "stream": True})
            self.assertEqual(release.saved_manifest["schema"], facade.SCHEMA)
            self.assertEqual(set(release.saved_manifest["images"]), set(release.activated_services))

    def test_real_subclass_super_container_still_uses_overridden_host_run(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            release = ProbeRelease(Path(directory))
            result = release.container("backend")
            self.assertTrue(result["State"]["Running"])
            self.assertEqual(release.events[0], ("container-override", "backend"))
            self.assertEqual(
                [event[1][:2] for event in release.events[1:]],
                [
                    ("docker", "ps"),
                    ("docker", "inspect"),
                ],
            )

    def test_standalone_cli_imports_from_unrelated_cwd_without_operational_credentials(self):
        script = Path(facade.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            for option, expected in (("--help", 0), ("--unrecognized", 2)):
                result = subprocess.run(
                    [sys.executable, str(script), option],
                    cwd=directory,
                    env={
                        "PATH": os.environ["PATH"],
                        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                        "PYTHONPATH": "",
                        "PYTHONNOUSERSITE": "1",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
