"""Exercise the actual QA entry point without Docker, native images or HTTP."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qa import qualify_api_native_memory as qualifier

IMAGE = "sha256:" + "a" * 64
CONTAINER = "c" * 64


class ApiProbeDocker:
    def __init__(self, root: Path):
        self.root = root
        self.calls = []
        self.running = False
        self.host_source = b"synthetic host admission source\n"
        self.image_source = self.host_source
        self.failure = None
        self.body_error = None
        self.run_error = None
        self.name, self.labels = None, {}
        for relative, content in (
            ("scripts/qa/api_native_memory_app.py", b"synthetic QA application\n"),
            ("backend/app/core/native_image_admission.py", self.host_source),
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def __call__(self, *arguments, **_kwargs):
        self.calls.append(arguments)
        if arguments[:3] == ("docker", "image", "inspect"):
            return IMAGE
        if arguments[:2] == ("docker", "run"):
            if "--detach" in arguments:
                self.running = True
                self.name = arguments[arguments.index("--name") + 1]
                self.labels = dict(
                    arguments[index + 1].split("=", 1)
                    for index, value in enumerate(arguments)
                    if value == "--label"
                )
                if self.run_error:
                    raise self.run_error
                return CONTAINER
            fixtures = next(self.root.glob("outputs/memory-qualification/*/fixtures"))
            (fixtures / "input.png").write_bytes(b"synthetic fixture only")
            (fixtures / "input.sha256").write_text("b" * 64)
            return ""
        if arguments[:2] == ("docker", "inspect"):
            if self.failure and self.failure[0] == "inspect":
                raise self.failure[1]
            return json.dumps(
                [
                    {
                        "Id": CONTAINER,
                        "Image": IMAGE,
                        "Name": "/" + self.name,
                        "Config": {"Labels": self.labels},
                        "State": {"Running": self.running},
                    }
                ]
            )
        if arguments[:2] == ("docker", "top"):
            return "PID PPID COMMAND\n100 1 synthetic gunicorn\n"
        if arguments[:2] == ("docker", "exec"):
            if arguments[-1] == "/qa/api_native_memory_app.py":
                if self.body_error:
                    raise self.body_error
                return json.dumps({"initial": {}, "rounds": [], "final": {}})
            if "native_image_admission.py" in arguments[-1]:
                return hashlib.sha256(self.image_source).hexdigest()
            return "{}"
        if arguments[:2] == ("docker", "logs"):
            if self.failure and self.failure[0] == "logs":
                raise self.failure[1]
            return "synthetic server log"
        if arguments[:2] == ("docker", "stop"):
            assert arguments[-1] == CONTAINER
            self.running = False
            return ""
        raise AssertionError(arguments)

    def receipt(self):
        return json.loads(
            next(
                self.root.glob("outputs/memory-qualification/*/evidence.json")
            ).read_text()
        )


class ApiNativeMemoryLifetimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.docker = ApiProbeDocker(self.root)
        self.enterContext(patch.object(qualifier, "ROOT", self.root))
        self.enterContext(patch.object(qualifier, "command", self.docker))
        self.enterContext(
            patch("sys.argv", ["qualify_api_native_memory.py", "--image", IMAGE])
        )

    def test_healthy_entry_point_retains_a_stopped_owned_probe_and_measurements(self):
        qualifier.main()
        self.assertFalse(self.docker.running)
        self.assertEqual(self.docker.receipt()["status"], "passed")
        self.assertEqual(self.docker.receipt()["image"], IMAGE)
        self.assertEqual(self.docker.receipt()["results"]["rounds"], [])

    def test_diagnostic_failure_cannot_bypass_owned_teardown_or_erase_evidence(self):
        for phase in ("inspect", "logs"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                docker = ApiProbeDocker(Path(directory))
                original = RuntimeError("synthetic " + phase + " diagnostic failure")
                docker.failure = phase, original
                with (
                    patch.object(qualifier, "ROOT", docker.root),
                    patch.object(qualifier, "command", docker),
                    self.assertRaises(RuntimeError) as raised,
                ):
                    qualifier.main()
                self.assertIs(raised.exception, original)
                self.assertFalse(docker.running)
                self.assertNotEqual(docker.receipt().get("status"), "passed")

    def test_probe_error_keeps_its_identity_when_secondary_diagnostics_fail(self):
        original = subprocess.CalledProcessError(
            7, ["synthetic probe"], output="synthetic output"
        )
        self.docker.body_error = original
        self.docker.failure = "logs", RuntimeError("secondary diagnostic failure")
        with self.assertRaises(Exception) as raised:
            qualifier.main()
        self.assertIs(raised.exception, original)
        self.assertFalse(self.docker.running)

    def test_non_overlay_receipt_binds_the_measured_image_source_not_the_host(self):
        self.docker.image_source = b"different retained immutable image admission\n"
        qualifier.main()
        receipt = self.docker.receipt()
        self.assertFalse(receipt["source_admission_overlay"])
        self.assertEqual(
            receipt["admission_sha256"],
            hashlib.sha256(self.docker.image_source).hexdigest(),
        )
        self.assertNotEqual(
            receipt["admission_sha256"],
            hashlib.sha256(self.docker.host_source).hexdigest(),
        )

    def test_verified_overlay_keeps_its_effective_source_binding(self):
        with patch(
            "sys.argv",
            ["qualify_api_native_memory.py", "--image", IMAGE, "--source-admission"],
        ):
            qualifier.main()
        receipt = self.docker.receipt()
        self.assertTrue(receipt["source_admission_overlay"])
        self.assertEqual(receipt["admission_sha256"], receipt["host_admission_sha256"])

    def test_overlay_mismatch_fails_before_workload_but_finishes_owned_container(self):
        self.docker.image_source = b"synthetic mismatching mounted source"
        with (
            patch(
                "sys.argv",
                [
                    "qualify_api_native_memory.py",
                    "--image",
                    IMAGE,
                    "--source-admission",
                ],
            ),
            self.assertRaisesRegex(ValueError, "overlay differs"),
        ):
            qualifier.main()
        self.assertFalse(self.docker.running)
        self.assertEqual(self.docker.receipt()["status"], "failed")
        self.assertFalse(
            any(
                call[-1] == "/qa/api_native_memory_app.py" for call in self.docker.calls
            )
        )

    def test_ambiguous_created_acquisition_keeps_original_error_after_exact_owned_drain(
        self,
    ):
        original = subprocess.TimeoutExpired("synthetic detached run", 120)
        self.docker.run_error = original
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            qualifier.main()
        self.assertIs(raised.exception, original)
        self.assertFalse(self.docker.running)
        self.assertEqual(self.docker.receipt()["container"], CONTAINER)
        self.assertEqual(self.docker.receipt()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
