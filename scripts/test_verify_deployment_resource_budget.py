"""Offline release-preflight regressions; run with unittest, without Docker."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from verify_deployment_resource_budget import validate_budget


def service(memory: object = "1g", cpus: object = "0.5", **extra: object) -> dict:
    return {"mem_limit": memory, "cpus": cpus, **extra}


class ResourceBudgetTests(unittest.TestCase):
    def test_accepts_exact_envelope_with_integer_and_compose_byte_units(self) -> None:
        config = {"services": {"api": service(1024**3), "db": service("1.5GB")}}
        failures, total = validate_budget(config, 4.5, 2)
        self.assertEqual((failures, total), ([], 2.5))

    def test_host_reserve_cannot_be_spent_on_containers(self) -> None:
        failures, total = validate_budget({"services": {"api": service("3g")}}, 4, 2)
        self.assertEqual(total, 3)
        self.assertTrue(any("exceed" in failure for failure in failures))

    def test_missing_or_invalid_services_never_pass(self) -> None:
        for config in (
            {},
            [],
            {"services": {}},
            {"services": []},
            {"services": {"api": None}},
        ):
            with self.subTest(config=config):
                self.assertTrue(validate_budget(config, 8, 2)[0])

    def test_nonfinite_or_negative_host_inputs_never_pass(self) -> None:
        config = {"services": {"api": service()}}
        for host, reserve in (
            (float("nan"), 2),
            (float("inf"), 2),
            (0, 2),
            (-1, 2),
            (8, -1),
            (8, float("nan")),
            (8, float("inf")),
        ):
            with self.subTest(host=host, reserve=reserve):
                self.assertTrue(validate_budget(config, host, reserve)[0])

    def test_invalid_memory_never_subtracts_from_other_services(self) -> None:
        for memory in (
            -(1024**3),
            0,
            True,
            None,
            "nan",
            "-1g",
            "0.1b",
            "${UNRESOLVED}",
            [],
            {},
        ):
            with self.subTest(memory=memory):
                config = {"services": {"bad": service(memory), "api": service("6g")}}
                failures, total = validate_budget(config, 7, 2)
                self.assertEqual(total, 6)
                self.assertTrue(any("bad:" in failure for failure in failures))
                self.assertTrue(any("exceed" in failure for failure in failures))

    def test_cpu_ceiling_must_be_explicit_positive_and_finite(self) -> None:
        for cpus in (None, True, 0, -1, "NaN", "Infinity", "${CPUS}", [], {}):
            with self.subTest(cpus=cpus):
                self.assertTrue(
                    validate_budget({"services": {"api": service(cpus=cpus)}}, 8, 2)[0]
                )

    def test_replica_count_contributes_to_budget(self) -> None:
        for extra in (
            {"scale": 3},
            {"deploy": {"replicas": 3}},
            {"scale": 3, "deploy": {"replicas": 3}},
        ):
            with self.subTest(extra=extra):
                failures, total = validate_budget(
                    {"services": {"api": service(**extra)}}, 4, 2
                )
                self.assertEqual(total, 3)
                self.assertTrue(any("exceed" in failure for failure in failures))

    def test_invalid_or_unbounded_replica_configuration_never_passes(self) -> None:
        for extra in (
            {"scale": -1},
            {"scale": True},
            {"scale": 1.5},
            {"deploy": {"mode": "global"}},
            {"deploy": []},
            {"scale": 2, "deploy": {"replicas": 3}},
        ):
            with self.subTest(extra=extra):
                self.assertTrue(
                    validate_budget({"services": {"api": service(**extra)}}, 16, 2)[0]
                )

    def test_explicit_zero_replicas_and_profile_services_are_accounted(self) -> None:
        config = {
            "services": {
                "disabled": service(scale=0),
                "optional": service(profiles=["reports"]),
            }
        }
        self.assertEqual(validate_budget(config, 3, 2), ([], 1))

    def test_worker_maximum_memory_is_checked_for_all_supported_syntaxes(self) -> None:
        for options in (
            ["--concurrency=8"],
            ["--concurrency", "8"],
            ["-c", "8"],
            ["-c8"],
            ["--autoscale=8,0"],
            ["--autoscale", "8,1"],
        ):
            with self.subTest(options=options):
                command = ["celery", "-A", "app.worker", "worker", *options]
                for rendered_command in (command, " ".join(command)):
                    failures, _ = validate_budget(
                        {"services": {"worker": service(command=rendered_command)}},
                        8,
                        2,
                    )
                    self.assertTrue(
                        any("worker count" in failure for failure in failures)
                    )

    def test_worker_exact_floor_passes_and_beat_is_not_a_worker(self) -> None:
        config = {
            "services": {
                "worker": service(
                    "512m",
                    command=["python", "-m", "celery", "worker", "--concurrency=2"],
                ),
                "beat": service("256m", command="celery -A app.worker beat"),
            }
        }
        self.assertEqual(validate_budget(config, 4, 2), ([], 0.75))

    def test_worker_implicit_or_malformed_limits_never_pass(self) -> None:
        for options in (
            [],
            ["-c", "0"],
            ["--concurrency=-1"],
            ["--concurrency"],
            ["--autoscale=2,3"],
            ["--autoscale=0,0"],
            ["--autoscale=2"],
            ["--concurrency=${WORKERS}"],
        ):
            with self.subTest(options=options):
                command = ["celery", "worker", *options]
                self.assertTrue(
                    validate_budget(
                        {"services": {"worker": service(command=command)}}, 8, 2
                    )[0]
                )

    def test_malformed_command_errors_do_not_echo_sensitive_arguments(self) -> None:
        command = "celery worker --concurrency=2 --password 'private-value"
        failures, _ = validate_budget(
            {"services": {"worker": service(command=command)}}, 8, 2
        )
        self.assertTrue(failures)
        self.assertNotIn("private-value", " ".join(failures))

    def test_cli_success_failure_and_private_invalid_json(self) -> None:
        script = Path(__file__).with_name("verify_deployment_resource_budget.py")
        with tempfile.TemporaryDirectory() as temporary:
            config_file = Path(temporary) / "compose.json"
            config_file.write_text(
                json.dumps({"services": {"api": service()}}), encoding="utf-8-sig"
            )
            command = [
                sys.executable,
                str(script),
                str(config_file),
                "--host-memory-gib",
            ]
            good = subprocess.run(
                [*command, "3"], capture_output=True, text=True, check=False
            )
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertIn("Memory envelope verified", good.stdout)
            overcommitted = subprocess.run(
                [*command, "2"], capture_output=True, text=True, check=False
            )
            self.assertEqual(overcommitted.returncode, 1)
            nonfinite = subprocess.run(
                [*command, "nan"], capture_output=True, text=True, check=False
            )
            self.assertEqual(nonfinite.returncode, 2)
            config_file.write_text(
                '{"secret": "private-value", invalid}', encoding="utf-8"
            )
            invalid = subprocess.run(
                [*command, "3"], capture_output=True, text=True, check=False
            )
            self.assertEqual(invalid.returncode, 2)
            self.assertNotIn("private-value", invalid.stderr)
            self.assertNotIn("Traceback", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
