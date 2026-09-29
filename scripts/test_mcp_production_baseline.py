"""Baseline collection binds one live project and emits no credentials or raw errors."""

import copy
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_production_baseline import (
    DIRECTORY,
    PROJECT,
    SERVICE,
    BaselineError,
    collect,
    memory_snapshot,
    run,
)
from release_traveller_whatsapp import ReleaseError

MEMORY = "MemTotal: 16384000 kB\nMemAvailable: 9500000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("/opt/application")
        self.containers = []
        for index, service in enumerate(("backend", "db", "unrelated"), 1):
            self.containers.append({"Id": str(index) * 64, "Image": "sha256:" + str(index) * 64,
                "Config": {"Labels": {PROJECT: "app" if index < 3 else "other", SERVICE: service,
                    DIRECTORY: str(self.root) if index < 3 else "/opt/other", "com.docker.compose.oneoff": "False"},
                    "Env": ["POSTGRES_HOST=db", "POSTGRES_PORT=5432", "POSTGRES_DB=app", "POSTGRES_PASSWORD=private-password",
                            "APP_SECRET_KEY=private-key", "WHATSAPP_ACCESS_TOKEN=private-token", "APP_REVISION=" + "a" * 40,
                            "EXPECTED_DATABASE_SCHEMA_REVISION=0113_document_follow_up", "WEB_CONCURRENCY=4", "MCP_ENABLED=false"]},
                "State": {"Running": True, "OOMKilled": False},
                "HostConfig": {"Memory": 1024**3, "MemorySwap": 1024**3, "NanoCpus": 10**9},
                "NetworkSettings": {"Networks": {"app": {"NetworkID": "private-network", "Aliases": [service]}}}})
        self.schema = {"schema": "0113_document_follow_up", "max_connections": 100,
                       "total_connections": 8, "database_connections": 6, "has_mcp_control": False}
        self.commands = []

    def runner(self, *arguments):
        self.commands.append(arguments)
        if arguments[:3] == ("docker", "context", "inspect"):
            return "unix:///var/run/docker.sock"
        if arguments[:3] == ("docker", "ps", "-aq"):
            return "\n".join(item["Id"] for item in self.containers)
        if arguments[:2] == ("docker", "inspect"):
            return json.dumps([item for item in self.containers if item["Id"] in arguments[2:]])
        if arguments[:2] == ("docker", "exec"):
            return "f" if arguments[-1].startswith("SELECT enabled") else json.dumps(self.schema)
        if arguments[:2] == ("docker", "stats"):
            return "\n".join(json.dumps({"ID": item["Id"], "CPUPerc": "2.3%", "MemUsage": "512MiB / 1GiB",
                "MemPerc": "50.0%", "PIDs": "9"}) for item in self.containers if item["Id"] in arguments)
        raise AssertionError(arguments)

    def collect(self):
        with patch.dict("os.environ", {}, clear=True):
            return collect(self.root, runner=self.runner, memory=MEMORY)

    def test_exact_project_snapshot_redacts_credentials_and_retains_unrelated_count_only(self):
        report = self.collect()
        self.assertEqual(report["database"]["schema"], self.schema["schema"])
        self.assertEqual(report["unrelated_container_count"], 1)
        self.assertEqual(report["unrelated_running_container_count"], 1)
        self.assertEqual(report["host_running_memory_limit_bytes"], 3 * 1024**3)
        self.assertEqual(report["host_running_unbounded_memory_count"], 0)
        self.assertEqual(len(report["containers"]), 2)
        self.assertEqual(report["containers"][0]["configuration"]["WEB_CONCURRENCY"], 4)
        self.assertFalse(report["containers"][0]["configuration"]["mcp_deployment_enabled"])
        self.assertNotIn("private-", json.dumps(report))
        self.assertNotIn("unrelated\"", json.dumps(report))
        self.assertEqual({command[1] for command in self.commands}, {"context", "ps", "inspect", "exec", "stats"})
        self.assertTrue(all(command[-1].startswith("SELECT") for command in self.commands if command[1] == "exec"))

    def test_actual_control_state_is_read_only_when_its_table_exists(self):
        self.schema.update(schema="0121_whatsapp_send_intents", has_mcp_control=True)
        report = self.collect()
        self.assertFalse(report["database"]["mcp_emergency_enabled"])
        self.assertEqual(sum(command[1] == "exec" for command in self.commands), 2)

    def test_wrong_or_ambiguous_live_target_is_refused(self):
        original = copy.deepcopy(self.containers)
        self.containers.append(copy.deepcopy(self.containers[0]))
        self.containers[-1]["Id"] = "4" * 64
        with self.assertRaisesRegex(BaselineError, "Exactly one"):
            self.collect()
        self.containers = original
        self.containers[0]["Config"]["Env"].append("POSTGRES_HOST=external")
        with self.assertRaisesRegex(ReleaseError, "identity/settings"):
            self.collect()

    def test_remote_docker_context_and_incomplete_usage_are_refused(self):
        def remote(*arguments):
            return "tcp://unrelated.example:2376"
        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(BaselineError, "local Docker"):
            collect(self.root, runner=remote, memory=MEMORY)
        def missing(*arguments):
            return "" if arguments[:2] == ("docker", "stats") else self.runner(*arguments)
        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(BaselineError, "incomplete"):
            collect(self.root, runner=missing, memory=MEMORY)
        with patch.dict("os.environ", {"DOCKER_HOST": "tcp://elsewhere"}), self.assertRaises(BaselineError):
            collect(self.root, runner=self.runner, memory=MEMORY)

    def test_malformed_database_observation_and_missing_host_fields_fail_closed(self):
        self.schema["total_connections"] = "private-database-exception"
        with self.assertRaisesRegex(BaselineError, "invalid bounded"):
            self.collect()
        with self.assertRaisesRegex(BaselineError, "incomplete"):
            memory_snapshot("MemTotal: 16384000 kB")

    def test_raw_probe_errors_never_reach_the_caller(self):
        failed = subprocess.CompletedProcess(("docker", "inspect"), 1, "private-config", "private-password")
        with patch("mcp_production_baseline.subprocess.run", return_value=failed), self.assertRaises(BaselineError) as error:
            run("docker", "inspect", "1" * 64)
        self.assertNotIn("private-", str(error.exception))


if __name__ == "__main__":
    unittest.main()
