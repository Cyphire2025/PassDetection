"""Source-schema retry retains previous evidence and cannot forgive new OOMs."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mcp_direct_build import BuildError
from mcp_direct_retry import bind_retry_baseline
from mcp_direct_state import INFRASTRUCTURE, SERVICES


class RetryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.activation = Mock()
        del self.activation._retry_baseline_path
        self.activation.state.directory = self.directory
        self.activation.state.revision = "e" * 40
        self.activation.schema.return_value = "0113_document_follow_up"
        self.activation.candidates.return_value = {}
        self.activation.originals = {
            service: {
                "Id": f"{index:064x}",
                "State": {"Running": True, "Health": {"Status": "healthy"}},
                "Config": {},
            }
            for index, service in enumerate(sorted(SERVICES), 1)
        }
        self.stage = {
            "containers": {
                name: {
                    "id": row["Id"],
                    "started_at": "old",
                    "restarts": 0,
                    "oom_killed": name == "nginx",
                    "events": {
                        "oom": 151 if name == "nginx" else 0,
                        "oom_kill": 3 if name == "nginx" else 0,
                    },
                }
                for name, row in self.activation.originals.items()
            }
        }
        self.current = copy.deepcopy(self.stage)
        for service in SERVICES - INFRASTRUCTURE - {"backend"}:
            self.current["containers"][service].update(
                started_at="recovered",
                oom_killed=False,
                events={"oom": 0, "oom_kill": 0},
            )
            row = self.current["containers"][service]
            (self.directory / f"oom-original-start-{row['id']}-test.json").write_text(
                json.dumps({"containers": {service: row}})
            )
        self.stage_path = self.directory / "oom-stage.private.json"
        self.stage_path.write_text(json.dumps(self.stage))
        self.original_bytes = self.stage_path.read_bytes()
        self.path = self.directory / "oom-retry-second.private.json"
        self.addCleanup(patch.stopall)
        patch("mcp_direct_retry.bound_original", side_effect=lambda row: row).start()
        self.command = patch(
            "mcp_direct_retry.command",
            return_value="\n".join(
                row["Id"] for row in self.activation.originals.values()
            ),
        ).start()
        self.capture = patch(
            "mcp_direct_retry.capture",
            side_effect=lambda rows, **kw: {
                "containers": {
                    key: copy.deepcopy(self.current["containers"][key]) for key in rows
                }
            },
        ).start()
        patch(
            "mcp_direct_retry._overlay_sources",
            return_value={"test": {"sha256": "f" * 64}},
        ).start()

    def test_recovered_app_zero_counters_bind_new_snapshot_without_replacing_history(
        self,
    ):
        result = bind_retry_baseline(self.activation, self.path)
        self.assertEqual(self.stage_path.read_bytes(), self.original_bytes)
        self.assertEqual(result["retry"]["schema"], "0113_document_follow_up")
        self.assertIn("nginx", result["retry"]["recovered_services"])
        self.activation.memory_checkpoint("before-drain", self.activation.originals)
        self.activation.state.event.assert_called_once()
        self.activation.client.assert_not_called()

    def test_infrastructure_or_continuous_backend_restart_is_not_forgiven(self):
        for service in ("db", "backend"):
            with self.subTest(service=service):
                previous = self.current["containers"][service]["started_at"]
                self.current["containers"][service]["started_at"] = "unexpected"
                with self.assertRaises(BuildError):
                    bind_retry_baseline(self.activation, self.path)
                self.current["containers"][service]["started_at"] = previous
        self.assertFalse(self.path.exists())

    def test_restarted_app_new_oom_or_restart_is_rejected(self):
        for field in ("oom", "oom_kill", "restarts", "oom_killed"):
            row = self.current["containers"]["nginx"]
            target = row["events"] if field in row["events"] else row
            target[field] = 1
            with self.subTest(field=field), self.assertRaises(BuildError):
                bind_retry_baseline(self.activation, self.path)
            target[field] = False if field == "oom_killed" else 0

    def test_continuous_original_new_oom_rejected(self):
        self.current["containers"]["backend"]["events"]["oom"] = 1
        with self.assertRaises(BuildError):
            bind_retry_baseline(self.activation, self.path)

    def test_backend_recovery_requires_its_exact_retained_start_evidence(self):
        row = self.current["containers"]["backend"]
        row["started_at"] = "recovered-backend"
        with self.assertRaisesRegex(BuildError, "start_receipt_unavailable"):
            bind_retry_baseline(self.activation, self.path)
        (self.directory / f"oom-original-start-{row['id']}-later.json").write_text(
            json.dumps({"containers": {"backend": row}})
        )
        result = bind_retry_baseline(self.activation, self.path)
        self.assertIn("backend", result["retry"]["recovery_receipts"])

    def test_target_schema_or_unexpected_running_helper_blocks_before_capture(self):
        self.activation.schema.return_value = "0122_mcp_gc_push"
        with self.assertRaisesRegex(BuildError, "original_schema"):
            bind_retry_baseline(self.activation, self.path)
        self.activation.schema.return_value = "0113_document_follow_up"
        self.command.return_value += "\n" + "f" * 64
        with self.assertRaisesRegex(BuildError, "inventory_changed"):
            bind_retry_baseline(self.activation, self.path)
        self.capture.assert_not_called()

    def test_unhealthy_or_stopped_original_blocks_before_snapshot(self):
        row = self.activation.originals["frontend"]["State"]
        for field, value in (
            ("Running", False),
            ("Health", {"Status": "starting"}),
            ("Paused", True),
        ):
            saved = row.get(field)
            row[field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(BuildError, "not_healthy"),
            ):
                bind_retry_baseline(self.activation, self.path)
            row[field] = saved
        self.assertFalse(self.path.exists())

    def test_existing_receipt_invalid_path_and_restaging_cannot_overwrite(self):
        self.path.write_text("retained")
        with self.assertRaisesRegex(BuildError, "explicit_snapshot"):
            bind_retry_baseline(self.activation, self.path)
        self.assertEqual(self.path.read_text(), "retained")
        with self.assertRaisesRegex(BuildError, "explicit_snapshot"):
            bind_retry_baseline(
                self.activation, self.directory / "oom-stage.private.json"
            )

    def test_bound_checkpoints_detect_new_oom_and_baseline_tampering(self):
        bind_retry_baseline(self.activation, self.path)
        self.current["containers"]["nginx"]["events"]["oom"] = 1
        with self.assertRaisesRegex(BuildError, "new_oom"):
            self.activation.memory_checkpoint(
                "before-stop-nginx", {"nginx": self.activation.originals["nginx"]}
            )
        self.path.write_text("{}")
        with self.assertRaisesRegex(BuildError, "baseline_or_inventory"):
            self.activation.memory_checkpoint("before-drain", self.activation.originals)
        with self.assertRaisesRegex(BuildError, "cannot_restage"):
            self.activation.memory_checkpoint(
                "stage", self.activation.originals, first=True
            )


if __name__ == "__main__":
    unittest.main()
