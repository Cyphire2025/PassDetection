"""Offline release regression tests; no Docker daemon, VPS, or subprocess is used.

python3 -m unittest discover -s scripts -p test_release_traveller_whatsapp.py
"""

from __future__ import annotations

import copy
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_traveller_whatsapp import (
    ACTIVATED,
    CONTROL_PROBE,
    NODE_PREFIXES,
    PREVIOUS_SCHEMA,
    PROBE_MARKER,
    PROJECT_LABEL,
    SCHEMA,
    SERVICE_LABEL,
    WORKERS,
    Release,
    ReleaseError,
    image_reference,
    updated_environment,
    validate_worker_probe,
)

REVISION = "a" * 40
OLD_REVISION = "b" * 40
NEW_BACKEND = "sha256:" + "1" * 64
NEW_WORKER = "sha256:" + "2" * 64
NEW_FRONTEND = "sha256:" + "3" * 64
OLD_IMAGE = "sha256:" + "4" * 64


class FakeDocker:
    """Stateful fake for subprocess.run, including image/container distinctions."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[list[str]] = []
        self.project = "globalconnectsdashboard"
        self.head = REVISION
        self.dirty = False
        self.schema = PREVIOUS_SCHEMA
        self.fail_migration = False
        self.fail_service: str | None = None
        self.public_status = "200"
        self.busy_on_probe = 0
        self.probe_count = 0
        self.probe_method = "active"
        self.untracked = ""
        self.on_build = None
        self.refs = {service: "passdetection-backend" for service in WORKERS}
        self.refs.update(
            backend=f"{self.project}-backend", frontend=f"{self.project}-frontend"
        )
        self.images: dict[str, dict] = {}
        self.containers = {
            service: self.make_container(service) for service in (*ACTIVATED, "nginx")
        }

    def make_container(self, service: str, image: str = OLD_IMAGE) -> dict:
        return {
            "Id": f"container-{service}",
            "Image": image,
            "State": {"Running": True},
            "Config": {
                "Hostname": f"host-{service}",
                "Env": [
                    f"APP_REVISION={OLD_REVISION}",
                    f"EXPECTED_DATABASE_SCHEMA_REVISION={PREVIOUS_SCHEMA}",
                ],
                "Labels": {
                    PROJECT_LABEL: self.project,
                    SERVICE_LABEL: service,
                    "com.docker.compose.project.working_dir": str(self.root),
                },
            },
        }

    def config(self) -> dict:
        services = {service: {"image": self.refs[service]} for service in WORKERS}
        services.update(
            backend={"build": {"context": "backend"}},
            frontend={"build": {"context": "frontend"}},
            nginx={"image": "nginx:known"},
        )
        values = dict(
            line.split("=", 1)
            for line in (self.root / ".env").read_text().splitlines()
            if "=" in line
        )
        for service in (*WORKERS, "backend"):
            services[service]["environment"] = dict(
                values, EXPECTED_DATABASE_SCHEMA_REVISION=SCHEMA
            )
        return {"name": self.project, "services": services}

    def build_images(self) -> None:
        for service, reference in self.refs.items():
            image_id = (
                NEW_FRONTEND
                if service == "frontend"
                else NEW_BACKEND
                if service == "backend"
                else NEW_WORKER
            )
            value = {
                "Id": image_id,
                "Config": {
                    "Env": [f"APP_REVISION={REVISION}"],
                    "Labels": {"org.opencontainers.image.revision": REVISION},
                },
            }
            self.images[reference] = value
            self.images[image_id] = value

    def run(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["APP_REVISION"] == REVISION
        assert kwargs["env"]["EXPECTED_DATABASE_SCHEMA_REVISION"] == SCHEMA
        code = 0
        output = ""
        if args[0] == "git":
            if args[1:3] == ["rev-parse", "HEAD"]:
                output = self.head
            elif args[1] == "diff":
                code = int(self.dirty)
            elif args[1] == "ls-files":
                output = self.untracked
            elif args[1] != "merge-base":
                raise AssertionError(f"Unexpected Git command: {args}")
        elif args[:2] == ["docker", "inspect"]:
            identifier = args[-1]
            service = (
                "backend"
                if identifier == "passdetection-backend"
                else identifier.removeprefix("container-")
            )
            output = json.dumps([self.containers[service]])
        elif args[:3] == ["docker", "image", "inspect"]:
            output = json.dumps([self.images[args[-1]]])
        elif args[:2] == ["docker", "compose"]:
            tail = args[8:]
            pin_path = None
            if tail[:1] == ["-f"]:
                pin_path = Path(tail[1])
                tail = tail[2:]
            if tail[:1] == ["config"]:
                output = (
                    "\n".join(set(self.refs.values()) | {"nginx:known"})
                    if "--images" in tail
                    else json.dumps(self.config())
                )
            elif tail[:1] == ["build"]:
                self.build_images()
                if self.on_build:
                    self.on_build()
            elif tail[:2] == ["ps", "--quiet"]:
                output = self.containers[tail[-1]]["Id"]
            elif tail[:1] == ["ps"]:
                output = "all services running"
            elif tail[:1] == ["exec"]:
                if CONTROL_PROBE in tail:
                    position = tail.index(CONTROL_PROBE)
                    nodes = json.loads(tail[position + 1])
                    idle = tail[position + 2] == "idle"
                    methods = ("active", "reserved", "scheduled") if idle else ("ping",)
                    payload = {
                        method: {node: [] if idle else {"ok": "pong"} for node in nodes}
                        for method in methods
                    }
                    if idle:
                        self.probe_count += 1
                        if self.probe_count == self.busy_on_probe:
                            payload[self.probe_method][nodes[0]] = [
                                {"id": "still-processing"}
                            ]
                    output = PROBE_MARKER + json.dumps(payload)
                else:
                    output = "ok"
            elif tail[:1] == ["run"]:
                assert pin_path is not None
                pins = json.loads(pin_path.read_text())["services"]
                assert pins["backend"]["image"] == NEW_BACKEND
                assert "--no-deps" in tail and "--rm" in tail
                if tail[-1] == "current":
                    output = self.schema + " (head)"
                elif tail[-2:] == ["upgrade", SCHEMA]:
                    code = int(self.fail_migration)
                    if not code:
                        self.schema = SCHEMA
                else:
                    raise AssertionError(f"Unexpected migration command: {tail}")
            elif tail[:1] == ["up"]:
                assert pin_path is not None
                assert "--no-deps" in tail and "--no-build" in tail and "--wait" in tail
                assert tail[tail.index("--timeout") + 1] == "60"
                pins = json.loads(pin_path.read_text())["services"]
                for service in [item for item in tail if item in ACTIVATED]:
                    if service == self.fail_service:
                        continue  # Compose returning success cannot substitute for image verification.
                    self.containers[service]["Image"] = pins[service]["image"]
                    self.containers[service]["Config"]["Env"] = [
                        f"APP_REVISION={REVISION}",
                        f"EXPECTED_DATABASE_SCHEMA_REVISION={SCHEMA}",
                    ]
                    self.containers[service]["Config"]["Hostname"] = (
                        f"new-host-{service}"
                    )
            else:
                raise AssertionError(f"Unexpected Compose command: {tail}")
        elif args[0] == "curl":
            output = self.public_status
        else:
            raise AssertionError(f"Unexpected command: {args}")
        return subprocess.CompletedProcess(
            args, code, stdout=output, stderr="private diagnostic: never print this"
        )

    def commands(self, token: str) -> list[list[str]]:
        return [call for call in self.calls if token in call]


class ProbeTests(unittest.TestCase):
    def test_fail_closed_missing_busy_and_malformed_worker_replies(self) -> None:
        nodes = {f"{prefix}@host" for prefix in NODE_PREFIXES.values()}
        valid = {
            method: {node: [] for node in nodes}
            for method in ("active", "reserved", "scheduled")
        }
        validate_worker_probe(valid, nodes, idle=True)
        failures = [None, {}, {"active": valid["active"]}]
        for method in valid:
            for bad in (
                None,
                {},
                {"unexpected@host": []},
                {node: [] for node in sorted(nodes)[:-1]},
            ):
                value = copy.deepcopy(valid)
                value[method] = bad
                failures.append(value)
            for bad in (None, "[]", {}, [{"id": "pending-job"}]):
                value = copy.deepcopy(valid)
                value[method][next(iter(nodes))] = bad
                failures.append(value)
        for payload in failures:
            with self.subTest(payload=payload), self.assertRaises(ReleaseError):
                validate_worker_probe(payload, nodes, idle=True)

    def test_compose_image_resolution_uses_actual_rendered_names(self) -> None:
        config = {
            "name": "vps",
            "services": {"backend": {}, "worker": {"image": "shared"}},
        }
        self.assertEqual(
            image_reference(config, {"vps-backend", "shared"}, "backend"), "vps-backend"
        )
        self.assertEqual(
            image_reference(config, {"vps_backend", "shared"}, "backend"), "vps_backend"
        )
        self.assertEqual(
            image_reference(config, {"vps_backend", "shared"}, "worker"), "shared"
        )
        for images in ({"unrelated"}, {"vps-backend", "vps_backend"}):
            with self.assertRaises(ReleaseError):
                image_reference(config, images, "backend")

    def test_environment_update_preserves_secrets_and_replaces_duplicate_pins(
        self,
    ) -> None:
        original = 'PASSWORD="preserve exactly # this"\nAPP_REVISION=old\nexport APP_REVISION=older\nEXPECTED_DATABASE_SCHEMA_REVISION=0092_old\n'
        result = updated_environment(original, REVISION)
        self.assertIn('PASSWORD="preserve exactly # this"\n', result)
        self.assertEqual(result.count("APP_REVISION="), 1)
        self.assertIn(f"EXPECTED_DATABASE_SCHEMA_REVISION={SCHEMA}\n", result)


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original_env = f"PASSWORD=private-test-value\nAPP_REVISION={OLD_REVISION}\nEXPECTED_DATABASE_SCHEMA_REVISION={PREVIOUS_SCHEMA}\n"
        (self.root / ".env").write_text(self.original_env)
        self.fake = FakeDocker(self.root)
        self.patch = patch(
            "release_traveller_whatsapp.subprocess.run", side_effect=self.fake.run
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.release = Release(REVISION, self.root)

    def test_complete_release_pins_images_migrates_and_activates_workers_before_web(
        self,
    ) -> None:
        self.release.prepare()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands("up"))
        self.assertFalse(self.fake.commands("upgrade"))
        self.release.activate()
        self.assertEqual(self.fake.schema, SCHEMA)
        up = self.fake.commands("up")
        self.assertEqual(
            [value for value in up[0] if value in ACTIVATED], list(WORKERS)
        )
        self.assertEqual(up[1][-1], "backend")
        self.assertEqual(up[2][-1], "frontend")
        self.assertLess(
            self.fake.calls.index(self.fake.commands("upgrade")[0]),
            self.fake.calls.index(up[0]),
        )
        self.assertEqual(self.fake.probe_count, 2)
        pins = json.loads(self.release.pin_path.read_text())["services"]
        self.assertEqual(pins["frontend"]["image"], NEW_FRONTEND)
        self.assertTrue(
            all(pins[service]["image"] == NEW_WORKER for service in WORKERS)
        )
        self.assertTrue(all(value["pull_policy"] == "never" for value in pins.values()))
        self.assertEqual(
            (self.release.directory / f"{REVISION}.env.backup").read_text(),
            self.original_env,
        )
        self.assertIn(
            f"EXPECTED_DATABASE_SCHEMA_REVISION={SCHEMA}",
            (self.root / ".env").read_text(),
        )
        self.assertEqual(len(self.fake.commands("curl")), 2)
        self.assertIn("RELEASE VERIFIED", self.output.getvalue())
        self.assertNotIn("private-test-value", self.output.getvalue())
        self.assertFalse(
            any(
                set(call) & {"down", "kill", "purge", "reset", "stash"}
                for call in self.fake.calls
            )
        )

    def test_busy_tasks_stop_before_environment_or_database_changes(self) -> None:
        self.release.prepare()
        self.fake.busy_on_probe = 1
        self.fake.probe_method = "scheduled"
        with self.assertRaisesRegex(ReleaseError, "scheduled:.*busy"):
            self.release.activate()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))

    def test_jobs_arriving_during_migration_stop_worker_activation(self) -> None:
        self.release.prepare()
        self.fake.busy_on_probe = 2
        self.fake.probe_method = "reserved"
        with self.assertRaisesRegex(ReleaseError, "reserved:.*busy"):
            self.release.activate()
        self.assertEqual(self.fake.schema, SCHEMA)
        self.assertFalse(self.fake.commands("up"))
        # The deliberate .env revision update must not prevent a safe retry.
        self.fake.busy_on_probe = 0
        self.release.activate()
        self.assertIn("RELEASE VERIFIED", self.output.getvalue())
        self.assertEqual(
            (self.release.directory / f"{REVISION}.env.backup").read_text(),
            self.original_env,
        )

    def test_atomic_write_does_not_touch_an_existing_generic_temporary_file(
        self,
    ) -> None:
        existing = self.root / ".env.tmp"
        existing.write_text("belongs to another tool")
        self.release.write_private(self.root / ".env", "replacement\n")
        self.assertEqual(existing.read_text(), "belongs to another tool")
        self.assertEqual((self.root / ".env").read_text(), "replacement\n")
        self.assertEqual(list(self.root.glob(".traveller-release-*")), [])

    def test_migration_failure_does_not_activate_any_service(self) -> None:
        self.release.prepare()
        self.fake.fail_migration = True
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertFalse(self.fake.commands("up"))
        self.assertEqual(self.fake.schema, PREVIOUS_SCHEMA)

    def test_image_retag_after_prepare_is_rejected_before_mutation(self) -> None:
        self.release.prepare()
        self.fake.images[self.fake.refs["frontend"]]["Id"] = "sha256:" + "9" * 64
        with self.assertRaisesRegex(ReleaseError, "image tag changed"):
            self.release.activate()
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertEqual((self.root / ".env").read_text(), self.original_env)

    def test_changed_secret_or_configuration_requires_preparation_again(self) -> None:
        self.release.prepare()
        (self.root / ".env").write_text(self.original_env + "NEW_SETTING=changed\n")
        with self.assertRaisesRegex(ReleaseError, "does not match"):
            self.release.activate()
        self.assertFalse(self.fake.commands("upgrade"))

    def test_configuration_change_during_build_never_creates_manifest(self) -> None:
        self.fake.on_build = lambda: (self.root / ".env").write_text(
            self.original_env + "NEW_SETTING=changed\n"
        )
        with self.assertRaisesRegex(ReleaseError, "changed during"):
            self.release.prepare()
        self.assertFalse(self.release.manifest_path.exists())

    def test_wrong_checkout_and_dirty_files_are_preserved_and_not_built(self) -> None:
        self.fake.head = OLD_REVISION
        with self.assertRaisesRegex(ReleaseError, "Checkout does not match"):
            self.release.prepare()
        self.fake.head = REVISION
        self.fake.dirty = True
        with self.assertRaises(ReleaseError):
            self.release.prepare()
        self.fake.dirty = False
        self.fake.untracked = "backend/unreviewed.py"
        with self.assertRaisesRegex(ReleaseError, "Untracked application"):
            self.release.prepare()
        self.assertFalse(self.fake.commands("build"))

    def test_worker_image_mismatch_prevents_web_activation(self) -> None:
        self.release.prepare()
        self.fake.fail_service = "visa-ai-worker"
        with self.assertRaisesRegex(ReleaseError, "visa-ai-worker: running image"):
            self.release.activate()
        self.assertEqual(len(self.fake.commands("up")), 1)

    def test_public_readiness_failure_cannot_report_verified(self) -> None:
        self.release.prepare()
        self.fake.public_status = "503"
        with self.assertRaisesRegex(ReleaseError, "did not return HTTP 200"):
            self.release.activate()
        self.assertNotIn("RELEASE VERIFIED", self.output.getvalue())

    def test_other_schema_is_not_implicitly_upgraded(self) -> None:
        self.release.prepare()
        self.fake.schema = "0091_qualifier_other_relation"
        with self.assertRaisesRegex(ReleaseError, "no broader migration"):
            self.release.activate()
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))

    def test_activation_requires_prepared_manifest_and_full_revision(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "No prepared release"):
            self.release.activate()
        with self.assertRaisesRegex(ReleaseError, "full 40-character"):
            Release("main", self.root)


if __name__ == "__main__":
    unittest.main()
