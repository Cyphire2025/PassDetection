"""Real activation ownership/dispatch with synthetic state and no Docker."""

import hashlib
import json
import os
import pickle
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import MethodType
from typing import get_type_hints
from unittest.mock import Mock, patch

import mcp_activation_database as database
import mcp_activation_lifecycle as lifecycle
import mcp_activation_readiness as readiness
import mcp_direct_activate as facade
import mcp_direct_retry as retry
import release_document_resources as resources
from mcp_direct_build import BuildError


class ProbeActivation(facade.DirectActivation):
    def await_health(self, candidates: dict, timeout: int = 180) -> None:
        self.health_calls += 1
        return super().await_health(candidates, timeout)


class ActivationOwnerTests(unittest.TestCase):
    def test_public_aliases_and_static_only_bases_preserve_descriptors_and_hints(self):
        self.assertEqual(
            [cls.__name__ for cls in facade.DirectActivation.__mro__[1:-1]],
            [
                "_ActivationReadiness",
                "_ActivationDatabase",
                "_ActivationStaging",
                "_ActivationIdentity",
            ],
        )
        for cls in facade.DirectActivation.__mro__[1:-1]:
            self.assertEqual(get_type_hints(cls), {})
            for name in ("__init__", "__slots__", "__getattr__", "state", "client"):
                self.assertNotIn(name, vars(cls))
        self.assertEqual(get_type_hints(facade.DirectActivation), {})
        for value in (
            facade.DirectActivation,
            facade.DirectActivation.await_health,
            facade.clean_stop,
        ):
            self.assertIs(pickle.loads(pickle.dumps(value)), value)
        self.assertEqual(get_type_hints(facade.DirectActivation.await_health)["return"], type(None))

    def test_actual_constructor_keeps_defaults_and_exact_image_bindings(self):
        revision = "d" * 40
        baseline = {
            "containers": {
                name: {"Image": "sha256:" + "a" * 64} for name in ("backend", "frontend")
            }
        }
        images = {
            "revision": revision,
            **{
                name: {"base_image_id": "sha256:" + "a" * 64, "image_id": "sha256:" + value * 64}
                for name, value in (("backend", "b"), ("frontend", "c"))
            },
        }
        state = Mock(revision=revision)
        state.load_baseline.return_value = baseline
        client = Mock()

        def inspect(*args):
            self.assertEqual(args[:3], ("docker", "image", "inspect"))
            return json.dumps(
                [
                    {
                        "Id": args[-1],
                        "Config": {"Labels": {"org.opencontainers.image.revision": revision}},
                    }
                ]
            )

        with tempfile.TemporaryDirectory() as directory:
            state.directory = Path(directory)
            (state.directory / "images.json").write_text(json.dumps(images), encoding="utf-8")
            with (
                patch.object(lifecycle, "LocalDocker", return_value=client),
                patch.object(lifecycle, "command", side_effect=inspect) as command,
            ):
                result = facade.DirectActivation(state)
            self.assertEqual(command.call_count, 2)
            self.assertIs(result.client, client)
            self.assertIs(result.originals, baseline["containers"])
            self.assertEqual(result.project, "mcp-direct-" + revision[:12])
            self.assertEqual(result.candidate_receipt, "candidates.private.json")

    def test_actual_subclass_super_dispatch_reaches_owned_health_gate(self):
        value = object.__new__(ProbeActivation)
        value.health_calls = 0
        row = {"Config": {}, "State": {"Running": True, "Health": {"Status": "healthy"}}}
        with (
            patch.object(readiness, "bound_original", return_value=row),
            patch.object(readiness.time, "monotonic", return_value=0),
        ):
            value.await_health({"backend": row}, timeout=1)
        self.assertEqual(value.health_calls, 1)

    def test_retry_style_instance_method_override_remains_authoritative_in_fence(self):
        value = object.__new__(facade.DirectActivation)
        value.state = Mock()
        value.baseline = {}
        names = facade.WRITERS | facade.INFRASTRUCTURE
        value.originals = {
            name: {
                "Id": f"{index:064x}",
                "State": {"Running": name in facade.INFRASTRUCTURE, "ExitCode": 0},
                "Config": {"Labels": {"com.docker.compose.service": name}},
                "NetworkSettings": {"Networks": {}},
            }
            for index, name in enumerate(sorted(names), 1)
        }
        value.candidates = Mock(return_value={})
        calls = []

        def checkpoint(instance, label, rows, *, first=False):
            self.assertIs(instance, value)
            calls.append((label, set(rows), first))

        value.memory_checkpoint = MethodType(checkpoint, value)
        with (
            patch.object(database, "bound_original", side_effect=lambda row: row),
            patch.object(
                database,
                "command",
                return_value="\n".join(
                    value.originals[name]["Id"] for name in facade.INFRASTRUCTURE
                ),
            ),
        ):
            value.fence()
        self.assertEqual(calls, [("fenced-infrastructure", facade.INFRASTRUCTURE, False)])
        value.state.verify_source.assert_called_once_with()
        value.state.verify_retention.assert_called_once_with(value.baseline)

    def test_actual_overlay_and_resource_source_bindings_cover_every_new_owner(self):
        names = {
            "mcp_activation_" + part
            for part in ("contract", "identity", "staging", "database", "readiness", "lifecycle")
        }
        self.assertLessEqual(names, set(retry.OVERLAY_MODULES))
        actual = retry._overlay_sources()
        self.assertEqual(set(actual), set(retry.OVERLAY_MODULES))
        for name in names:
            path = Path(sys.modules[name].__file__).resolve()
            self.assertEqual(
                actual[name],
                {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
            )
            self.assertIn("scripts/" + name + ".py", resources.QUALIFIED_SOURCES)
        self.assertIn("scripts/mcp_direct_activate.py", resources.QUALIFIED_SOURCES)
        with patch.dict(sys.modules, {"mcp_activation_readiness": None}):
            with self.assertRaisesRegex(BuildError, "^retry_overlay_module_unavailable$"):
                retry._overlay_sources()

    def test_documented_cli_and_fresh_facade_import_work_without_credentials(self):
        root = Path(__file__).resolve().parents[1]
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
        env["PYTHONPATH"] = ""
        with tempfile.TemporaryDirectory() as directory:
            for args, status in (
                ([str(root / "scripts/mcp_direct_release.py"), "--help"], 0),
                ([str(root / "scripts/mcp_direct_release.py"), "--invalid-release-flag"], 2),
                (
                    [
                        "-c",
                        "import sys;sys.path.insert(0,"
                        + repr(str(root / "scripts"))
                        + ");import mcp_direct_activate as m;assert m.DirectActivation.__module__=='mcp_direct_activate'",
                    ],
                    0,
                ),
            ):
                result = subprocess.run(
                    [sys.executable, "-B", *args],
                    cwd=directory,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, status, result.stderr)


if __name__ == "__main__":
    unittest.main()
