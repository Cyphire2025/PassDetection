"""Actual activation health gate with synthetic Docker records and clock only."""

import unittest
from unittest.mock import patch

import mcp_activation_readiness as health_owner
import mcp_direct_activate as activation
from mcp_direct_build import BuildError


def running(*, healthcheck=None, health=None):
    return {
        "Config": {"Healthcheck": healthcheck},
        "State": {"Running": True, "Health": {} if health is None else {"Status": health}},
        "RestartCount": 0,
    }


class DirectHealthAdmission(unittest.TestCase):
    def execute(self, rows, clock):
        deployment = object.__new__(activation.DirectActivation)
        with (
            patch.object(health_owner, "bound_original", side_effect=rows) as inspect,
            patch.object(activation.time, "monotonic", side_effect=clock),
            patch.object(activation.time, "sleep") as sleep,
        ):
            deployment.await_health({"backend": {"Id": "synthetic"}}, timeout=1)
        return inspect, sleep

    def test_absent_or_explicitly_disabled_check_keeps_existing_admission(self):
        for check in (None, {}, {"Test": ["NONE"]}):
            with self.subTest(check=check):
                inspect, sleep = self.execute([running(healthcheck=check)], [0, 0, 0.1])
                self.assertEqual(inspect.call_count, 1)
                sleep.assert_not_called()

    def test_configured_check_cannot_admit_missing_or_unknown_health(self):
        for status in (None, "unknown"):
            with self.subTest(status=status):
                row = running(healthcheck={"Test": ["CMD", "synthetic-check"]}, health=status)
                with self.assertRaisesRegex(BuildError, "^candidate_health_deadline$"):
                    self.execute([row], [0, 0, 2])

    def test_healthy_response_after_deadline_cannot_authorize_cutover(self):
        row = running(healthcheck={"Test": ["CMD", "synthetic-check"]}, health="healthy")
        with self.assertRaisesRegex(BuildError, "^candidate_health_deadline$"):
            self.execute([row], [0, 0, 2])

    def test_starting_waits_then_healthy_admits_with_original_poll_interval(self):
        rows = [
            running(healthcheck={"Test": ["CMD", "synthetic-check"]}, health=state)
            for state in ("starting", "healthy")
        ]
        inspect, sleep = self.execute(rows, [0, 0, 0.1, 0.2, 0.3])
        self.assertEqual(inspect.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_unhealthy_still_rejects_immediately(self):
        row = running(health="unhealthy")
        with self.assertRaisesRegex(BuildError, "^candidate_health_failed$"):
            self.execute([row], [0, 0])

    def test_exited_oom_or_restarted_candidate_still_rejects_immediately(self):
        for mutation in ("exited", "oom", "restarted"):
            with self.subTest(mutation=mutation):
                row = running(health="healthy")
                if mutation == "exited":
                    row["State"]["Running"] = False
                elif mutation == "oom":
                    row["State"]["OOMKilled"] = True
                else:
                    row["RestartCount"] = 1
                with self.assertRaisesRegex(BuildError, "^candidate_exit_oom_or_restart$"):
                    self.execute([row], [0, 0])


if __name__ == "__main__":
    unittest.main()
