"""Exact cutover ordering and pre-upgrade recovery, without Docker mutations."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import Mock, patch

from mcp_direct_activate import ORIGIN, TARGET, WRITERS, DirectActivation, clean_stop
from mcp_direct_build import GIB, BuildError
from mcp_direct_release import resume_original_workers
from mcp_direct_state import INFRASTRUCTURE, WORKERS
from test_mcp_direct_containers import original


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.deployment = object.__new__(DirectActivation)
        self.events = []
        self.state = self.deployment.state = Mock()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state.directory = Path(temporary.name)
        self.state.revision = "d" * 40
        self.state.event.side_effect = lambda name, **kw: self.events.append(
            ("event", name)
        )
        self.deployment.project = "mcp-direct-test"
        self.deployment.client = Mock()
        self.originals = {}
        for index, service in enumerate(sorted(WRITERS | INFRASTRUCTURE), 1):
            row = original(service)
            row["Id"] = f"{index:064x}"
            row["State"].update(ExitCode=0, OOMKilled=service == "nginx")
            row["RestartCount"] = 0
            self.originals[service] = row
        self.deployment.originals = copy.deepcopy(self.originals)
        self.deployment.baseline = {"containers": self.deployment.originals}
        self.rows = {row["Id"]: row for row in self.originals.values()}
        self.candidate_rows = {}
        for index, service in enumerate(sorted(WRITERS), 100):
            row = original(service)
            row["Id"] = f"{index:064x}"
            row["State"].update(Running=False, ExitCode=0, OOMKilled=False)
            row["RestartCount"] = 0
            self.candidate_rows[service] = row
            self.rows[row["Id"]] = row
        self.deployment.candidates = Mock(return_value=self.candidate_rows)
        self.deployment.schema = Mock(return_value="0113_document_follow_up")
        self.deployment.client.graceful_stop.side_effect = self.stop
        self.deployment.start = Mock(side_effect=self.start)
        self.deployment.migrate = Mock(
            side_effect=lambda: self.events.append(("migrate",))
        )
        self.deployment.await_health = Mock(
            side_effect=lambda rows: self.events.append(("health", set(rows)))
        )
        self.deployment.verify = Mock(
            side_effect=lambda: self.events.append(("verify",))
        )
        self.deployment.memory_checkpoint = Mock()
        self.addCleanup(patch.stopall)
        patch(
            "mcp_direct_activate.bound_original",
            side_effect=lambda row: self.rows[row["Id"]],
        ).start()
        self.command = patch(
            "mcp_direct_activate.command", side_effect=self.run_command
        ).start()
        self.idle = patch(
            "mcp_direct_activate.require_idle",
            side_effect=lambda _: self.events.append(("idle",)),
        ).start()
        patch("mcp_direct_activate.capture_memory", side_effect=self.memory).start()

    def memory(self, rows, **kwargs):
        return {
            "containers": {
                service: {
                    "id": row["Id"],
                    "started_at": "current-start",
                    "restarts": 0,
                    "oom_killed": False,
                    "events": {"oom": 0, "oom_kill": 0},
                }
                for service, row in rows.items()
            }
        }

    def stop(self, identifier, **kwargs):
        row = self.rows[identifier]
        service = row["Config"]["Labels"]["com.docker.compose.service"]
        self.events.append(("stop", service))
        row["State"]["Running"] = False
        return row

    def start(self, row, service):
        self.events.append(("start", service))
        self.rows[row["Id"]]["State"]["Running"] = True

    def run_command(self, *args, **kwargs):
        if args == ("docker", "ps", "-q", "--no-trunc"):
            return "\n".join(
                key for key, row in self.rows.items() if row["State"]["Running"]
            )
        raise AssertionError(args)

    def stop_originals(self):
        for service in WRITERS:
            self.originals[service]["State"]["Running"] = False

    def test_cutover_stops_ingress_and_scheduler_then_drains_before_migration_and_proxy(
        self,
    ):
        self.deployment.activate()
        stops = [event[1] for event in self.events if event[0] == "stop"]
        self.assertEqual(
            stops, ["email-beat", "nginx", *WORKERS, "frontend", "backend"]
        )
        self.assertLess(
            self.events.index(("stop", "nginx")), self.events.index(("idle",))
        )
        self.assertLess(
            self.events.index(("idle",)), self.events.index(("stop", "worker"))
        )
        self.assertLess(
            self.events.index(("stop", "backend")), self.events.index(("migrate",))
        )
        self.assertLess(
            self.events.index(("migrate",)), self.events.index(("start", "worker"))
        )
        self.assertLess(
            self.events.index(("health", WRITERS - {"nginx"})),
            self.events.index(("start", "nginx")),
        )
        self.assertEqual(self.events[-1], ("verify",))

    def test_busy_workers_leave_backend_and_workers_running_without_migration(self):
        self.idle.side_effect = BuildError("busy")
        with self.assertRaisesRegex(BuildError, "busy"):
            self.deployment.activate()
        self.assertEqual(
            [event[1] for event in self.events if event[0] == "stop"],
            ["email-beat", "nginx"],
        )
        self.deployment.migrate.assert_not_called()
        self.deployment.start.assert_not_called()

    def test_failed_migration_never_starts_candidate_or_old_schema_client(self):
        self.deployment.migrate.side_effect = BuildError("forward_repair_required")
        with self.assertRaisesRegex(BuildError, "forward_repair"):
            self.deployment.activate()
        self.deployment.start.assert_not_called()
        self.assertTrue(
            all(not self.originals[name]["State"]["Running"] for name in WRITERS)
        )

    def test_wrong_start_schema_rejects_before_any_stop(self):
        self.deployment.schema.return_value = TARGET
        with self.assertRaises(BuildError):
            self.deployment.activate()
        self.deployment.client.graceful_stop.assert_not_called()

    def test_original_historic_oom_flag_is_retained_but_new_flag_or_restart_rejected(
        self,
    ):
        row = copy.deepcopy(self.originals["nginx"])
        row["State"]["Running"] = False
        clean_stop(row, self.originals["nginx"])
        with self.assertRaises(BuildError):
            clean_stop(row)
        row["RestartCount"] = 1
        with self.assertRaises(BuildError):
            clean_stop(row, self.originals["nginx"])
        row = copy.deepcopy(self.originals["backend"])
        row["State"].update(Running=False, OOMKilled=True)
        with self.assertRaises(BuildError):
            clean_stop(row, self.originals["backend"])

    def test_fence_requires_every_original_stopped_and_all_candidates_stopped(self):
        with self.assertRaises(BuildError):
            self.deployment.fence()
        self.stop_originals()
        self.deployment.fence()
        self.candidate_rows["worker"]["State"]["Running"] = True
        with self.assertRaisesRegex(BuildError, "candidate_writer"):
            self.deployment.fence()

    def test_fence_rejects_running_helper_or_changed_infrastructure_network(self):
        self.stop_originals()
        self.rows["f" * 64] = {"State": {"Running": True}}
        with self.assertRaisesRegex(BuildError, "unexpected_running"):
            self.deployment.fence()
        self.rows["f" * 64]["State"]["Running"] = False
        self.originals["db"]["NetworkSettings"]["Networks"]["original-net"][
            "NetworkID"
        ] = "changed"
        with self.assertRaisesRegex(BuildError, "network_binding"):
            self.deployment.fence()

    def test_explicit_original_recovery_only_starts_stopped_originals_proxy_last(self):
        self.stop_originals()
        self.deployment.recover_original()
        starts = [event[1] for event in self.events if event[0] == "start"]
        self.assertEqual(
            starts, [*WORKERS, "backend", "frontend", "email-beat", "nginx"]
        )
        self.assertGreaterEqual(self.deployment.schema.call_count, len(starts) + 1)
        self.state.verify_retention.assert_called_once()

    def test_recovery_refuses_target_schema_or_any_running_candidate_or_helper(self):
        self.stop_originals()
        self.deployment.schema.return_value = TARGET
        with self.assertRaisesRegex(BuildError, "source_schema"):
            self.deployment.recover_original()
        self.deployment.schema.return_value = "0113_document_follow_up"
        self.candidate_rows["backend"]["State"]["Running"] = True
        with self.assertRaisesRegex(BuildError, "candidate_running"):
            self.deployment.recover_original()
        self.candidate_rows["backend"]["State"]["Running"] = False
        self.rows["f" * 64] = {"State": {"Running": True}}
        with self.assertRaisesRegex(BuildError, "unexpected_running"):
            self.deployment.recover_original()
        self.deployment.start.assert_not_called()

    def test_recovery_validates_all_stopped_processes_before_first_start(self):
        self.stop_originals()
        self.originals["nginx"]["State"]["ExitCode"] = 137
        with self.assertRaisesRegex(BuildError, "cleanly_drained"):
            self.deployment.recover_original()
        self.deployment.start.assert_not_called()

    def test_start_admits_current_whole_host_budget_before_starting_container(self):
        self.command.side_effect = ["", str(16 * GIB)]
        DirectActivation.start(
            self.deployment, self.candidate_rows["backend"], "backend"
        )
        self.deployment.client.start.assert_called_once_with(
            self.candidate_rows["backend"]["Id"]
        )
        self.deployment.client.start.reset_mock()
        self.command.side_effect = ["", str(2 * GIB)]
        with self.assertRaisesRegex(BuildError, "host_reserve"):
            DirectActivation.start(
                self.deployment, self.candidate_rows["backend"], "backend"
            )
        self.deployment.client.start.assert_not_called()

    def test_verify_checks_real_disabled_control_revision_and_exact_metadata_path(self):
        self.stop_originals()
        self.deployment.schema.return_value = TARGET
        self.deployment.database_command = Mock(return_value="f")
        for service, candidate in self.candidate_rows.items():
            (self.state.directory / f"oom-start-{candidate['Id']}.json").write_text(
                json.dumps(self.memory({service: candidate}))
            )
        visited = []

        def response(request, **kwargs):
            self.assertTrue(request.get_header("User-agent").startswith("Mozilla/5.0"))
            url = request.full_url
            visited.append(url)
            payload = (
                {"revision": self.state.revision}
                if url.endswith("/live")
                else {"status": "ready"}
                if url.endswith("/ready")
                else {"resource": ORIGIN + "/mcp"}
            )
            result = Mock(status=200)
            result.read.return_value = json.dumps(payload).encode()
            manager = Mock()
            manager.__enter__ = Mock(return_value=result)
            manager.__exit__ = Mock(return_value=False)
            return manager

        with patch("mcp_direct_activate.urllib.request.urlopen", side_effect=response):
            DirectActivation.verify(self.deployment)
        self.assertEqual(
            visited[-1], ORIGIN + "/.well-known/oauth-protected-resource/mcp"
        )
        self.deployment.database_command.return_value = "t"
        with self.assertRaisesRegex(BuildError, "control_not_disabled"):
            DirectActivation.verify(self.deployment)

    def test_repeat_original_recovery_preserves_each_memory_receipt(self):
        self.command.side_effect = ["", str(16 * GIB), "", str(16 * GIB)]
        for _ in range(2):
            DirectActivation.start(self.deployment, self.originals["frontend"], "frontend")
        receipts = list(self.state.directory.glob("oom-original-start-*.json"))
        self.assertEqual(len(receipts), 2)
        self.assertEqual(self.deployment.client.start.call_count, 2)

    def test_migration_cannot_run_before_memory_admission_releases_unique_gate(self):
        helper = copy.deepcopy(self.candidate_rows["backend"])
        self.deployment.images = {"backend": {"image_id": helper["Image"]}}
        self.state.source = PurePosixPath("/opt/GlobalConnectsDashboard/tmp/mcp-direct-" + "d" * 40 + "/source")
        (self.state.directory / "migration-credentials.private.json").write_text(
            json.dumps({"POSTGRES_USER": "owner", "POSTGRES_PASSWORD": "test"})
        )
        self.deployment.fence = Mock()
        self.deployment.client.request.return_value = {"Id": helper["Id"]}
        backup = {"filename": "new.pgdump", "bytes": 1, "sha256": "f" * 64}
        request = {"image_id": helper["Image"], "environment": {},
                   "arguments": ["python", "scripts/apply_mcp_additive_upgrade.py"],
                   "timeout": 30, "proof": "f" * 64}
        def run(*arguments, **kwargs):
            if arguments[:2] == ("docker", "exec"):
                self.assertTrue(self.deployment.start.called)
                self.assertTrue(arguments[-1].startswith("/tmp/mcp-migration-"))
                self.events.append(("gate",))
                return ""
            if arguments[:2] == ("docker", "wait"):
                self.assertIn(("gate",), self.events)
                return "0"
            raise AssertionError(arguments)
        self.command.side_effect = run
        with patch("mcp_direct_activate.MCPDatabaseRelease") as database, patch(
            "mcp_direct_activate.inspect", return_value=helper
        ):
            database.return_value.backup.return_value = backup
            database.return_value.migration_request.return_value = request
            DirectActivation.migrate(self.deployment)
        payload = self.deployment.client.request.call_args.args[2]
        self.assertEqual(payload["Cmd"][-2:], request["arguments"])
        self.assertIn("os.execvp", payload["Cmd"][3])

    def test_stage_requires_running_originals_before_credentials_or_creates(self):
        with tempfile.TemporaryDirectory() as directory:
            self.state.directory = Path(directory)
            self.originals["worker"]["State"]["Running"] = False
            with self.assertRaisesRegex(BuildError, "original_services_running"):
                self.deployment.stage()
        self.command.assert_not_called()
        self.deployment.client.create_clone.assert_not_called()

    def test_separate_worker_resume_cannot_bypass_target_schema_or_helper_fence(self):
        with patch("mcp_direct_release.bound_original", side_effect=lambda row: row):
            with patch("mcp_direct_release.command", return_value=TARGET) as run:
                with self.assertRaisesRegex(BuildError, "source_release"):
                    resume_original_workers(self.state, self.deployment.baseline)
                self.assertFalse(
                    any(
                        call.args[:2] == ("docker", "start")
                        for call in run.call_args_list
                    )
                )
            with patch(
                "mcp_direct_release.command",
                side_effect=["0113_document_follow_up", "f" * 64],
            ) as run:
                with self.assertRaisesRegex(BuildError, "helper_or_candidate"):
                    resume_original_workers(self.state, self.deployment.baseline)
                self.assertFalse(
                    any(
                        call.args[:2] == ("docker", "start")
                        for call in run.call_args_list
                    )
                )


if __name__ == "__main__":
    unittest.main()
