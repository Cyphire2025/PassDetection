"""Retention and isolation invariants before a clone reaches the Docker socket."""
import copy
import unittest
from unittest.mock import patch

from mcp_direct_containers import ContainerError, LocalDocker, clone_payload


def original(service="backend"):
    return {"Id": "a" * 64, "Name": "/original", "Image": "sha256:" + "b" * 64,
            "Config": {"User": "1001:1001", "WorkingDir": "/app", "Env": ["SECRET=retained"],
                       "Labels": {"com.docker.compose.service": service}, "Cmd": ["gunicorn"]},
            "HostConfig": {"Memory": 256 * 1024**2, "MemorySwap": 0, "NanoCpus": 500000000,
                           "Privileged": False, "NetworkMode": "original-net", "CapDrop": ["ALL"],
                           "SecurityOpt": ["no-new-privileges:true"], "PortBindings": {},
                           "Binds": ["/source:/data:ro"]},
            "NetworkSettings": {"Networks": {"original-net": {"NetworkID": "c" * 64,
                                  "Aliases": ["backend", "original"], "IPAddress": "172.18.0.9", "MacAddress": "secret"}}},
            "State": {"Running": True}}


def options():
    return {"name": "candidate-backend", "image_id": "sha256:" + "d" * 64,
            "environment": {"SECRET": "retained", "MCP_ENABLED": "true"}, "new_project": "mcp-direct-abcd",
            "source_root": "/opt/GlobalConnectsDashboard/tmp/mcp-direct-" + "d" * 40 + "/source",
            "aliases": {"original-net": "candidate-backend"}}


class CloneTests(unittest.TestCase):
    def test_original_null_entrypoint_explicitly_clears_candidate_image_entrypoint(self):
        for entrypoint in (None, [], ["/original-entrypoint"]):
            source = original()
            source["Config"]["Entrypoint"] = entrypoint
            source["Config"]["Cmd"] = ["sh", "-c", "exec worker"]
            before = copy.deepcopy(source)
            payload = clone_payload(source, **options())
            self.assertEqual(payload["Entrypoint"], entrypoint or [])
            self.assertEqual(payload["Cmd"], ["sh", "-c", "exec worker"])
            self.assertEqual(source, before)

    def test_preserves_original_security_resources_mounts_and_does_not_mutate(self):
        source = original()
        before = copy.deepcopy(source)
        payload = clone_payload(source, **options())
        self.assertEqual(source, before)
        self.assertEqual(payload["HostConfig"], before["HostConfig"])
        self.assertEqual(payload["WorkingDir"], "/app")
        endpoint = payload["NetworkingConfig"]["EndpointsConfig"]["original-net"]
        self.assertEqual(endpoint, {"NetworkID": "c" * 64, "Aliases": ["candidate-backend"]})
        self.assertNotIn("172.18.0.9", str(payload))
        self.assertNotIn("MacAddress", str(payload))

    def test_infrastructure_unbounded_or_exposed_application_is_rejected(self):
        bad = [original("db"), original(), original(), original()]
        bad[1]["HostConfig"]["Memory"] = 0
        bad[2]["HostConfig"]["Privileged"] = True
        bad[3]["HostConfig"]["PortBindings"] = {"8000/tcp": [{"HostPort": "8000"}]}
        for source in bad:
            with self.subTest(source=source["HostConfig"]), self.assertRaises(ContainerError):
                clone_payload(source, **options())

    def test_alias_collision_is_rejected(self):
        args = options()
        args["aliases"]["original-net"] = "backend"
        with self.assertRaises(ContainerError):
            clone_payload(original(), **args)

    def test_proxy_only_changes_exact_readonly_configuration_binds(self):
        source, args = original("nginx"), options()
        source["HostConfig"]["Binds"] = ["/old/nginx.conf:/etc/nginx/nginx.conf:ro", "/old/conf.d:/etc/nginx/conf.d:ro", "/certs:/etc/nginx/certs:ro"]
        release_root = args["source_root"].removesuffix("/source")
        args["nginx_mount_overrides"] = {"/etc/nginx/nginx.conf": release_root + "/runtime-nginx/nginx.conf",
                                          "/etc/nginx/conf.d": release_root + "/runtime-nginx/conf.d"}
        payload = clone_payload(source, **args)
        self.assertIn("/certs:/etc/nginx/certs:ro", payload["HostConfig"]["Binds"])
        self.assertIn("/old/nginx.conf:/etc/nginx/nginx.conf:ro", source["HostConfig"]["Binds"])

    def test_timeout_never_escalates_to_kill_and_proxy_uses_quit(self):
        for service, expected in (("backend", "TERM"), ("nginx", "QUIT")):
            client = object.__new__(LocalDocker)
            with patch.object(client, "inspect", return_value=original(service)), patch.object(client, "request") as request, patch("mcp_direct_containers.time.monotonic", side_effect=[0, 2]), self.assertRaisesRegex(ContainerError, "still_draining"):
                client.graceful_stop("a" * 64, timeout=1)
            request.assert_called_once_with("POST", "/containers/" + "a" * 64 + "/kill?signal=" + expected)


if __name__ == "__main__":
    unittest.main()
