"""Configuration admission uses mocked Docker output; no containers are started."""

import copy
import json
import unittest
from unittest.mock import patch

import yaml
from mcp_capacity_profile import (
    CAPABILITIES,
    EXPORT_FAMILIES,
    SOURCE_BYTES,
    SOURCE_ROWS,
)
from qualify_workload_capacity import API_MEMORY_BYTES, ORIGIN, inspect_backend
from run_qualification_stack import ROOT


def backend_fixture():
    env = {
        "POSTGRES_DB": "passdetection_ci_browser",
        "WEB_CONCURRENCY": "4",
        "POSTGRES_API_POOL_SIZE": "3",
        "POSTGRES_API_MAX_OVERFLOW": "3",
        "MALWARE_SCANNER_TIMEOUT_SECONDS": "10.0",
        "MCP_ENABLED": "true",
        "MCP_PUBLIC_ORIGIN": ORIGIN,
        "MCP_FRONTEND_ORIGIN": ORIGIN,
        "MCP_ENABLED_CAPABILITIES": json.dumps(sorted(CAPABILITIES)),
        "MCP_EXPORT_FAMILIES": json.dumps(EXPORT_FAMILIES),
        "MCP_EXPORT_SOURCE_ROW_LIMIT": str(SOURCE_ROWS),
        "MCP_EXPORT_SOURCE_BYTE_LIMIT": str(SOURCE_BYTES),
    }
    return env, {
        "Config": {
            "Labels": {"com.docker.compose.project": "passdetection-qualification"},
            "Env": [],
        },
        "HostConfig": {
            "Memory": API_MEMORY_BYTES,
            "MemorySwap": API_MEMORY_BYTES,
            "NanoCpus": 4 * 10**9,
        },
    }


def inspect_mocked(env, container):
    container = copy.deepcopy(container)
    container["Config"]["Env"] = [f"{key}={value}" for key, value in env.items()]
    outputs = [json.dumps({"Project": "passdetection-qualification"}),
               "synthetic-backend-id", json.dumps([container])]
    with patch("qualify_workload_capacity.subprocess.check_output", side_effect=outputs) as command:
        result = inspect_backend()
        assert command.call_count == 3
    return result


class CapacityProfileAdmission(unittest.TestCase):
    def test_actual_compose_profile_matches_admission_without_relaxing_resources(self):
        compose = yaml.safe_load((ROOT / "docker-compose.capacity.yml").read_text("utf-8"))
        backend = compose["services"]["backend"]
        env, container = backend_fixture()
        env.update(backend["environment"])
        self.assertEqual(backend["mem_limit"], "2560m")
        self.assertEqual(backend["memswap_limit"], "2560m")
        self.assertEqual(backend["cpus"], 4)
        self.assertEqual(inspect_mocked(env, container)["HostConfig"], container["HostConfig"])

    def test_missing_broader_or_smaller_profile_fails_closed(self):
        for key, values in {
            "MCP_ENABLED": [None, "false"],
            "MCP_ENABLED_CAPABILITIES": [None, '["mcp:read","mcp:export","mcp:upload"]'],
            "MCP_EXPORT_FAMILIES": [None, '[]', '["passport_excel","passport_images_zip"]'],
            "MCP_EXPORT_SOURCE_ROW_LIMIT": [None, "99", "1500"],
            "MCP_EXPORT_SOURCE_BYTE_LIMIT": [None, "1024", "16777216"],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    env, container = backend_fixture()
                    if value is None:
                        del env[key]
                    else:
                        env[key] = value
                    with self.assertRaises(ValueError):
                        inspect_mocked(env, container)

    def test_minimum_mcp_profile_cannot_bypass_existing_isolation_or_resource_checks(self):
        for field, value in (("POSTGRES_DB", "production"), ("MCP_PUBLIC_ORIGIN", "https://example.invalid"),
                             ("WEB_CONCURRENCY", "8"), ("POSTGRES_API_MAX_OVERFLOW", "10")):
            with self.subTest(field=field):
                env, container = backend_fixture()
                env[field] = value
                with self.assertRaises(RuntimeError):
                    inspect_mocked(env, container)
        for field, value in (("Memory", API_MEMORY_BYTES + 1), ("MemorySwap", API_MEMORY_BYTES + 1),
                             ("NanoCpus", 8 * 10**9)):
            with self.subTest(field=field):
                env, container = backend_fixture()
                container["HostConfig"][field] = value
                with self.assertRaises(RuntimeError):
                    inspect_mocked(env, container)


if __name__ == "__main__":
    unittest.main()
