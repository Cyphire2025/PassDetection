"""Capacity and dependency invariants for the explicitly authorized direct lane."""
import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from mcp_direct_build import (
    GIB,
    NODE_IMAGE,
    BuildError,
    RetainedBuild,
    admit_builder,
    contract_digest,
    dependency_delta,
)
from mcp_direct_containers import ContainerError


def locked(name, version, marker=""):
    return f"{name}=={version}{marker} \\\n    --hash=sha256:{'a' * 64}\n    # via reviewed source\n"


class DirectBuildTests(unittest.TestCase):
    def test_only_reviewed_build_schema_identities_are_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertEqual(RetainedBuild(root, root, "a" * 40).schema_revision, "0122_mcp_gc_push")
            self.assertEqual(RetainedBuild(root, root, "a" * 40, schema_revision="0129_travel_tracker").schema_revision, "0129_travel_tracker")
            with self.assertRaisesRegex(BuildError, "unreviewed_build_schema"):
                RetainedBuild(root, root, "a" * 40, schema_revision="0130_unreviewed")

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
            builder.commit_runtime = Mock(return_value="sha256:" + "b" * 64)
            builder.backend("sha256:" + "a" * 64, previous)
            code = builder.create.call_args.args[4][1]
            final_call = ast.parse(code).body[-1].value
            self.assertEqual(ast.literal_eval(final_call.args[0]), ["/bin/chown", "-R", "1001:1001", "/app"])
            builder.commit_runtime.assert_called_once_with("a" * 64, "backend")

    def test_frontend_commits_the_prepared_runtime_through_the_same_verifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            builder = RetainedBuild(root, root, "e" * 40, run=Mock(return_value="b" * 64))
            builder.create = Mock(return_value="a" * 64)
            builder.existing = Mock(return_value=False)
            builder.execute = Mock(return_value={"exit_code": 0})
            builder.commit_runtime = Mock(return_value="sha256:" + "c" * 64)
            result = builder.frontend("sha256:" + "d" * 64, "https://tech.gctravels.com")
            self.assertEqual(builder.create.call_args.args[1], NODE_IMAGE)
            self.assertRegex(NODE_IMAGE, r'^node:24-alpine@sha256:[a-f0-9]{64}$')
            builder.commit_runtime.assert_called_once_with("b" * 64, "frontend")
            self.assertEqual(result["image_id"], "sha256:" + "c" * 64)

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


class RuntimeCommitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.identifier = "a" * 64
        self.image = "sha256:" + "b" * 64
        self.container = {
            "Id": self.identifier,
            "State": {"Running": False, "ExitCode": 0, "OOMKilled": False},
            "Config": {
                "User": "0:0", "WorkingDir": "/builder",
                "Entrypoint": ["/usr/local/bin/python"], "Cmd": ["-c", "build()"],
                "Env": ["PATH=/opt/venv/bin:/usr/bin", "PYTHONPATH=/opt/mcp-deps:/app",
                        "APP_REVISION=old", "EXPECTED_DATABASE_SCHEMA_REVISION=0113_document_follow_up",
                        "NEXT_PUBLIC_APP_REVISION=old"],
                "Labels": {"retained": "yes"},
                "Healthcheck": {"Test": ["CMD", "python", "-m", "health"]},
                "StopSignal": "SIGTERM",
            },
        }
        self.client = Mock()
        self.client.request.return_value = {"Id": self.image}
        self.image_mutations = {}
        self.image_identity = self.image
        self.remove_entrypoint = False
        self.run = Mock(side_effect=self.command)
        self.builder = RetainedBuild(self.root, self.root, "e" * 40,
                                     run=self.run, client=self.client)

    def command(self, *args):
        if args == ("docker", "inspect", self.identifier):
            return json.dumps([self.container])
        if args == ("docker", "image", "inspect", self.image):
            config = copy.deepcopy(self.client.request.call_args.args[2])
            config.update(self.image_mutations)
            if self.remove_entrypoint:
                config.pop("Entrypoint")
            return json.dumps([{"Id": self.image_identity, "Config": config}])
        raise AssertionError(args)

    def test_explicit_empty_entrypoint_and_exact_runtime_config_for_both_images(self):
        before = copy.deepcopy(self.container)
        for family, expected_command, revision_key in (
            ("backend", ["gunicorn", "--config", "gunicorn.conf.py", "app.main:app"], "APP_REVISION"),
            ("frontend", ["node", "server.js"], "NEXT_PUBLIC_APP_REVISION"),
        ):
            with self.subTest(family=family):
                self.assertEqual(self.builder.commit_runtime(self.identifier, family), self.image)
                method, path, config = self.client.request.call_args.args
                self.assertEqual(self.client.request.call_args.kwargs, {"timeout": 120})
                self.assertEqual(method, "POST")
                self.assertEqual(urlsplit(path).path, "/commit")
                self.assertEqual(parse_qs(urlsplit(path).query),
                                 {"container": [self.identifier], "pause": ["false"]})
                self.assertEqual(config["Entrypoint"], [])
                self.assertEqual(config["Cmd"], expected_command)
                self.assertEqual(config["User"], "1001:1001")
                self.assertEqual(config["WorkingDir"], "/app")
                self.assertIn(revision_key + "=" + "e" * 40, config["Env"])
                self.assertNotIn(revision_key + "=old", config["Env"])
                self.assertIn("PYTHONPATH=/opt/mcp-deps:/app", config["Env"])
                if family == "backend":
                    self.assertIn("EXPECTED_DATABASE_SCHEMA_REVISION=0122_mcp_gc_push", config["Env"])
                self.assertEqual(config["Labels"], {"retained": "yes", "org.opencontainers.image.revision": "e" * 40})
                for key in ("Healthcheck", "StopSignal"):
                    self.assertEqual(config[key], before["Config"][key])
                self.assertEqual(self.container, before)
                self.assertEqual(self.run.call_args.args, ("docker", "image", "inspect", self.image))

    def test_docker_empty_null_or_omitted_entrypoint_preserves_explicit_commit_clear(self):
        for family in ("backend", "frontend"):
            for representation in ("empty", "null", "omitted"):
                with self.subTest(family=family, representation=representation):
                    self.remove_entrypoint = representation == "omitted"
                    self.image_mutations = {"Entrypoint": None if representation == "null" else []}
                    self.assertEqual(self.builder.commit_runtime(self.identifier, family), self.image)
                    self.assertEqual(self.client.request.call_args.args[2]["Entrypoint"], [])

    def test_same_schema_fast_image_records_the_actual_schema(self):
        builder = RetainedBuild(self.root, self.root, "e" * 40, run=self.run,
                                client=self.client, schema_revision="0129_travel_tracker")
        builder.commit_runtime(self.identifier, "backend")
        environment = self.client.request.call_args.args[2]["Env"]
        self.assertIn("EXPECTED_DATABASE_SCHEMA_REVISION=0129_travel_tracker", environment)
        self.assertNotIn("EXPECTED_DATABASE_SCHEMA_REVISION=0122_mcp_gc_push", environment)

    def test_inherited_commands_identity_or_revision_mismatch_reject_committed_image(self):
        cases = (
            {"Entrypoint": ["/usr/local/bin/python"]}, {"Entrypoint": ["/bin/sh"]},
            {"Entrypoint": ""}, {"Entrypoint": [""]}, {"Entrypoint": {}},
            {"Entrypoint": False}, {"Cmd": ["-c", "build()"]}, {"User": "0:0"},
            {"WorkingDir": "/builder"}, {"Env": ["APP_REVISION=old"]},
            {"Labels": {"org.opencontainers.image.revision": "f" * 40}},
            {"Healthcheck": {"Test": ["NONE"]}}, {"Healthcheck": None},
            {"StopSignal": "SIGKILL"}, {"StopSignal": None},
        )
        for mutation in cases:
            with self.subTest(mutation=mutation), self.assertRaisesRegex(BuildError, "committed_runtime_config_mismatch"):
                self.image_mutations = mutation
                self.builder.commit_runtime(self.identifier, "backend")
        self.assertFalse(any(call.args[:2] in {("docker", "rm"), ("docker", "rmi"), ("docker", "stop")}
                             for call in self.run.call_args_list))

    def test_omitted_entrypoint_does_not_bypass_other_runtime_checks(self):
        self.remove_entrypoint = True
        for mutation in ({"Cmd": ["-c", "build()"]}, {"User": "0:0"},
                         {"Env": ["APP_REVISION=old"]}, {"Healthcheck": None}):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(BuildError, "committed_runtime_config_mismatch"):
                self.image_mutations = mutation
                self.builder.commit_runtime(self.identifier, "backend")

    def test_restarted_failed_or_oom_builder_is_never_committed(self):
        for state in ({"Running": True}, {"ExitCode": 2}, {"OOMKilled": True}, {"Dead": True}):
            with self.subTest(state=state), self.assertRaisesRegex(BuildError, "successful_stopped_builder"):
                self.container["State"] = {"Running": False, "ExitCode": 0, "OOMKilled": False, **state}
                self.builder.commit_runtime(self.identifier, "backend")
        self.client.request.assert_not_called()

    def test_container_and_image_identity_substitutions_are_rejected(self):
        self.container["Id"] = "c" * 64
        with self.assertRaisesRegex(BuildError, "runtime_commit_container_changed"):
            self.builder.commit_runtime(self.identifier, "backend")
        self.client.request.assert_not_called()
        self.container["Id"] = self.identifier
        self.image_identity = "sha256:" + "c" * 64
        with self.assertRaisesRegex(BuildError, "committed_runtime_image_changed"):
            self.builder.commit_runtime(self.identifier, "backend")

    def test_invalid_commit_response_never_becomes_an_image_receipt(self):
        for response in (None, {}, {"Id": "tag:latest"}, {"Id": 5}):
            with self.subTest(response=response), self.assertRaisesRegex(BuildError, "invalid_built_image_identity"):
                self.client.request.return_value = response
                self.builder.commit_runtime(self.identifier, "backend")
        self.assertFalse(any(call.args[:3] == ("docker", "image", "inspect") for call in self.run.call_args_list))

    def test_uncertain_commit_stops_without_retry_or_success_receipt(self):
        self.client.request.side_effect = ContainerError("docker_request_failed")
        with self.assertRaisesRegex(ContainerError, "docker_request_failed"):
            self.builder.commit_runtime(self.identifier, "backend")
        self.client.request.assert_called_once()
        self.assertEqual(self.client.request.call_args.kwargs, {"timeout": 120})
        self.run.assert_called_once_with("docker", "inspect", self.identifier)


if __name__ == "__main__":
    unittest.main()
