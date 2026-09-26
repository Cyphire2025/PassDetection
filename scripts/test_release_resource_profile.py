"""The measured profile cannot silently gain workers, larger inputs or providers."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from image_runtime_policy import (
    BACKEND_PROCESSES,
    WORKER_COMMANDS,
    reviewed_process_command,
)
from release_resource_profile import (
    EXPECTED_ENV,
    PROVIDERS,
    validate_local_swap_free_host,
    validate_profile,
)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.metadata = json.loads((Path(__file__).resolve().parents[1] / "tooling/deployment-profiles/kvm4.json").read_text())
        self.metadata["qualification_status"] = "qualified"
        self.config = {"services": {name: {"mem_limit": size * 1024**2, "memswap_limit": size * 1024**2,
                                          "cpus": 4 if name == "backend" else 1}
                      for name, size in {**self.metadata["memory_limits_mib"], **self.metadata["maintenance_limits_mib"]}.items()}}
        for name in BACKEND_PROCESSES:
            self.config["services"][name]["environment"] = dict(EXPECTED_ENV)
        for name in ("nginx", "metrics-exporter"):
            self.config["services"][name].pop("memswap_limit")
        for name in WORKER_COMMANDS:
            self.config["services"][name]["command"] = reviewed_process_command(name)
        self.config["services"]["db"]["command"] = ["postgres", "-c", "max_connections=100"]
        for name, maximum in {"redis": 128, "redis-broker": 512, "redis-realtime": 128, "redis-cache": 256}.items():
            self.config["services"][name]["command"] = ["redis-server", "--maxmemory", f"{maximum}mb", "--maxmemory-policy",
                                                       "allkeys-lru" if name == "redis-cache" else "noeviction"]

    def verify(self, **kwargs):
        return validate_profile(self.config, self.metadata, activation=True, my_photos_jobs=0,
                                live_backend_environment={}, **kwargs)

    def test_exact_qualified_profile_passes(self):
        self.verify()

    def test_candidate_can_prepare_but_never_activate(self):
        self.metadata["qualification_status"] = "candidate_pending_final_application_and_lifecycle_checks"
        validate_profile(self.config, self.metadata, activation=False, my_photos_jobs=0, live_backend_environment={})
        with self.assertRaisesRegex(ValueError, "completed actual-image"):
            self.verify()

    def test_all_three_enabled_providers_and_existing_jobs_refused(self):
        for key in PROVIDERS:
            with self.subTest(key=key):
                self.config["services"]["backend"]["environment"][key] = "aws_rekognition"
                with self.assertRaisesRegex(ValueError, "Enabled My Photos"):
                    self.verify()
                del self.config["services"]["backend"]["environment"][key]
                with self.assertRaisesRegex(ValueError, "already enabled"):
                    validate_profile(self.config, self.metadata, activation=True, my_photos_jobs=0,
                                     live_backend_environment={key: "s3"})
        with self.assertRaisesRegex(ValueError, "empty existing job table"):
            validate_profile(self.config, self.metadata, activation=True, my_photos_jobs=1, live_backend_environment={})

    def test_cap_replicas_worker_queue_and_process_budget_cannot_drift(self):
        original = copy.deepcopy(self.config)
        changes = [lambda c: c["services"]["backend"].update(mem_limit="3g"),
                   lambda c: c["services"]["backend"].update(memswap_limit="3g"),
                   lambda c: c["services"]["worker"].update(scale=2),
                   lambda c: c["services"]["worker"].update(command=reviewed_process_command("worker", concurrency=2)),
                   lambda c: c["services"]["backend"]["environment"].update(WEB_CONCURRENCY="8"),
                   lambda c: c["services"]["worker"]["environment"].update(POSTGRES_WORKER_POOL_SIZE="2"),
                   lambda c: c["services"].update(extra={"mem_limit": "128m", "cpus": 1})]
        for mutate in changes:
            self.config = copy.deepcopy(original)
            mutate(self.config)
            with self.assertRaises(ValueError):
                self.verify()

    def test_accepted_input_maxima_cannot_exceed_qualification(self):
        for key, value in (("UPLOAD_MAX_FILE_SIZE_BYTES", 11 * 1024**2), ("UPLOAD_MAX_PIXELS", 25_000_000),
                           ("ECR_IMAGE_MAX_PIXELS", 41_000_000), ("EMAIL_ATTACHMENT_MAX_BYTES", 26 * 1024**2),
                           ("EMAIL_PDF_MAX_PAGES", 101), ("ECR_MAX_CONCURRENCY", 9), ("ECR_IMAGE_MAX_DIMENSION", 2001)):
            with self.subTest(key=key):
                self.config["services"]["worker"]["environment"][key] = str(value)
                with self.assertRaisesRegex(ValueError, "measured input envelope"):
                    self.verify()
                del self.config["services"]["worker"]["environment"][key]

    def test_redis_growth_duplicate_flags_and_eviction_drift_are_refused(self):
        original = copy.deepcopy(self.config)
        for name in ("redis", "redis-broker", "redis-realtime", "redis-cache"):
            for suffix in (["--maxmemory", "2gb"], ["--maxmemory-policy", "allkeys-random"]):
                self.config = copy.deepcopy(original)
                self.config["services"][name]["command"].extend(suffix)
                with self.assertRaises(ValueError):
                    self.verify()
            self.config = copy.deepcopy(original)
            self.config["services"][name]["command"][2] = "2gb"
            with self.assertRaisesRegex(ValueError, "Redis envelope"):
                self.verify()

    def test_swap_exception_rejects_remote_daemon_nonlinux_or_enabled_swap(self):
        with patch("release_resource_profile.sys.platform", "linux"), patch.object(Path, "stat", return_value=SimpleNamespace(st_mode=0o140600)):
            with patch.object(Path, "is_absolute", return_value=True), patch.object(Path, "read_text", return_value="SwapTotal: 0 kB\n"):
                validate_local_swap_free_host("unix:///var/run/docker.sock")
                with self.assertRaisesRegex(ValueError, "local Linux"):
                    validate_local_swap_free_host("tcp://host:2376")
            with (patch.object(Path, "is_absolute", return_value=True),
                  patch.object(Path, "read_text", return_value="SwapTotal: 1024 kB\n"),
                  self.assertRaisesRegex(ValueError, "zero configured")):
                validate_local_swap_free_host("unix:///var/run/docker.sock")
        with patch("release_resource_profile.sys.platform", "win32"), self.assertRaisesRegex(ValueError, "local Linux"):
            validate_local_swap_free_host("unix:///var/run/docker.sock")


if __name__ == "__main__":
    unittest.main()
