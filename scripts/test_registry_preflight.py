"""Registry protocol and actual promotion orchestration; no external writes."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import registry_preflight as registry
import release_artifacts as artifacts

REVISION = "a" * 40
REFERENCE = "ghcr.io/cyphire2025/passdetection-backend:" + REVISION
CHALLENGE = (
    401,
    {"www-authenticate": 'Bearer realm="https://ghcr.io/token",service="ghcr.io"'},
    b"",
)
TOKEN = (200, {}, b'{"token":"synthetic-bearer"}')
PROTOCOL = {"docker-distribution-api-version": "registry/2.0"}


class DockerCredentialTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        environment = patch.dict(os.environ, DOCKER_CONFIG=str(self.directory))
        environment.start()
        self.addCleanup(environment.stop)

    def config(self, document):
        (self.directory / "config.json").write_text(
            json.dumps(document), encoding="utf-8"
        )

    def test_inline_login_handles_colons_without_exposing_credentials(self):
        value = base64.b64encode(b"synthetic-user:synthetic:token").decode()
        self.config({"auths": {"ghcr.io": {"auth": value}}})
        self.assertEqual(
            registry.docker_credentials(), ("synthetic-user", "synthetic:token")
        )

    def test_registry_helper_precedes_global_store_and_uses_only_registry_stdin(self):
        self.config(
            {"credHelpers": {"ghcr.io": "test-helper"}, "credsStore": "other-helper"}
        )
        with patch(
            "registry_preflight.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 0, '{"Username":"synthetic-user","Secret":"synthetic-token"}', ""
            ),
        ) as helper:
            self.assertEqual(
                registry.docker_credentials(), ("synthetic-user", "synthetic-token")
            )
        self.assertEqual(
            helper.call_args.args[0], ["docker-credential-test-helper", "get"]
        )
        self.assertEqual(helper.call_args.kwargs["input"], "ghcr.io\n")
        self.assertNotIn("synthetic-token", repr(helper.call_args))

    def test_helper_failure_cannot_fall_back_to_anonymous_or_print_its_output(self):
        self.config({"credsStore": "test-helper"})
        with (
            patch(
                "registry_preflight.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 1, "private-value", "private-value"
                ),
            ),
            self.assertRaises(ValueError) as failure,
        ):
            registry.docker_credentials()
        self.assertNotIn("private-value", str(failure.exception))

    def test_bad_or_unsupported_login_fails_without_secret_echo(self):
        for document in (
            {},
            {"auths": {"ghcr.io": {"auth": "private-value"}}},
            {"credsStore": "../../private-value"},
        ):
            self.config(document)
            with (
                self.subTest(document=document),
                self.assertRaises(ValueError) as failure,
            ):
                registry.docker_credentials()
            self.assertNotIn("private-value", str(failure.exception))


class RegistryProtocolTests(unittest.TestCase):
    def check(self, final_response):
        with (
            patch(
                "registry_preflight.docker_credentials",
                return_value=("synthetic-user", "synthetic-secret"),
            ),
            patch(
                "registry_preflight._request",
                side_effect=[CHALLENGE, TOKEN, final_response],
            ) as request,
        ):
            answer = registry.registry_tag_exists(REFERENCE)
        return answer, request.call_args_list

    def test_first_publication_requires_authenticated_registry_404(self):
        answer, calls = self.check((404, PROTOCOL, b""))
        self.assertFalse(answer)
        self.assertEqual(len(calls), 3)
        self.assertIn(
            "scope=repository%3Acyphire2025%2Fpassdetection-backend%3Apull%2Cpush",
            calls[1].args[1],
        )
        self.assertEqual(calls[2].args[0], "HEAD")
        self.assertEqual(calls[2].args[2]["Authorization"], "Bearer synthetic-bearer")

    def test_existing_manifest_requires_digest_readback(self):
        self.assertTrue(
            self.check(
                (200, {**PROTOCOL, "docker-content-digest": "sha256:" + "b" * 64}, b"")
            )[0]
        )
        with self.assertRaises(ValueError):
            self.check((200, PROTOCOL, b""))

    def test_denied_redirect_server_error_or_unidentified_404_is_not_absence(self):
        for status in (401, 403, 302, 307, 429, 500, 503):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.check((status, PROTOCOL, b"private-value"))
        with self.assertRaises(ValueError):
            self.check((404, {}, b"not found"))

    def test_token_failure_or_foreign_challenge_stops_before_authenticated_head(self):
        for challenge in (
            'Bearer realm="https://attacker.invalid/token",service="ghcr.io"',
            'Bearer realm="http://ghcr.io/token",service="ghcr.io"',
            'Bearer realm="https://ghcr.io/token",service="other"',
            'Bearer realm="https://ghcr.io/token",realm="https://ghcr.io/token",service="ghcr.io"',
        ):
            with (
                patch(
                    "registry_preflight.docker_credentials",
                    return_value=("user", "private-value"),
                ),
                patch(
                    "registry_preflight._request",
                    return_value=(401, {"www-authenticate": challenge}, b""),
                ) as request,
                self.subTest(challenge=challenge),
                self.assertRaises(ValueError),
            ):
                registry.registry_tag_exists(REFERENCE)
            self.assertEqual(request.call_count, 1)
        with (
            patch(
                "registry_preflight.docker_credentials",
                return_value=("user", "private-value"),
            ),
            patch(
                "registry_preflight._request",
                side_effect=[CHALLENGE, (403, {}, b"private-value")],
            ) as request,
            self.assertRaises(ValueError) as failure,
        ):
            registry.registry_tag_exists(REFERENCE)
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("private-value", str(failure.exception))

    def test_invalid_token_payload_does_not_reach_manifest(self):
        for body in (
            b"private-value",
            b"[]",
            b"{}",
            b'{"token":"a","access_token":"b"}',
            b'{"token":"a\\r\\nHeader: private-value"}',
            b'{"token":"\\u0100"}',
        ):
            with (
                patch(
                    "registry_preflight.docker_credentials",
                    return_value=("user", "secret"),
                ),
                patch(
                    "registry_preflight._request",
                    side_effect=[CHALLENGE, (200, {}, body)],
                ) as request,
                self.subTest(body=body),
                self.assertRaises(ValueError) as failure,
            ):
                registry.registry_tag_exists(REFERENCE)
            self.assertEqual(request.call_count, 2)
            self.assertNotIn("private-value", str(failure.exception))

    def test_network_error_is_scrubbed_and_redirect_is_never_followed(self):
        with patch("registry_preflight.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.URLError(
                "private-value"
            )
            with self.assertRaises(ValueError) as failure:
                registry._request("GET", "https://ghcr.io/v2/", {})
        self.assertNotIn("private-value", str(failure.exception))
        self.assertIsNone(
            registry._NoRedirects().redirect_request(
                None, None, 302, "", {}, "https://attacker.invalid"
            )
        )


class PromotionFlowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.images = {}
        self.identifiers = {}
        self.qualified = {
            "version": 1,
            "revision": REVISION,
            "dependency_policy_sha256": "reviewed",
            "images": {},
            "deployment": artifacts.source_contract(artifacts.ROOT),
        }
        for name in artifacts.IMAGES:
            config = {
                "config": {"Labels": {"org.opencontainers.image.revision": REVISION}},
                "rootfs": {"diff_ids": []},
                "architecture": "amd64",
                "os": "linux",
            }
            raw = json.dumps(config).encode()
            identifier = "sha256:" + hashlib.sha256(raw).hexdigest()
            archive = self.directory / f"{name}.tar"
            with tarfile.open(archive, "w") as writer:
                for member_name, data in (
                    ("config.json", raw),
                    (
                        "manifest.json",
                        json.dumps(
                            [
                                {
                                    "Config": "config.json",
                                    "RepoTags": [f"passdetection-{name}:ci"],
                                }
                            ]
                        ).encode(),
                    ),
                ):
                    member = tarfile.TarInfo(member_name)
                    member.size = len(data)
                    writer.addfile(member, io.BytesIO(data))
            sbom = self.directory / f"{name}.spdx.json"
            sbom.write_text("{}")
            self.identifiers[name] = identifier
            self.images[name] = {
                "Id": identifier,
                "Config": config["config"],
                "RootFS": {"Layers": []},
                "Os": "linux",
                "Architecture": "amd64",
                "RepoDigests": [
                    f"{artifacts.trust_policy()['registry']}-{name}@sha256:" + "b" * 64
                ],
            }
            self.qualified["images"][name] = {
                "image_id": identifier,
                "archive_sha256": artifacts.sha256(archive),
                "sbom_sha256": artifacts.sha256(sbom),
            }
        (self.directory / "qualified-images.json").write_text(
            json.dumps(self.qualified)
        )
        self.commands = []
        self.remote_config = None

    def command(self, *args):
        self.commands.append(args)
        if args[:3] == ("gh", "attestation", "verify") or args[:2] in {
            ("docker", "load"),
            ("docker", "pull"),
            ("docker", "tag"),
            ("docker", "push"),
        }:
            return ""
        name = "backend" if "backend" in args[-1] else "frontend"
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([self.images[name]])
        if args[:3] == ("docker", "manifest", "inspect"):
            return json.dumps(
                {
                    "OCIManifest": {
                        "config": {
                            "digest": self.remote_config or self.identifiers[name]
                        }
                    }
                }
            )
        raise AssertionError(args)

    def promote(self, exists=False):
        with (
            patch("release_artifacts.run", side_effect=self.command),
            patch(
                "release_artifacts.dependency_policy_fingerprint",
                return_value="reviewed",
            ),
            patch(
                "release_artifacts.registry_tag_exists", return_value=exists
            ) as preflight,
        ):
            result = artifacts.promote(self.directory, REVISION, self.qualified["deployment"]["target_schema"])
        self.assertEqual(preflight.call_count, 2)
        return result

    def test_first_publication_promotes_only_verified_archive_bytes(self):
        result = self.promote()
        self.assertEqual(
            len(
                [
                    command
                    for command in self.commands
                    if command[:2] == ("docker", "push")
                ]
            ),
            2,
        )
        self.assertEqual(set(result["images"]), set(artifacts.IMAGES))
        self.assertTrue((self.directory / "release-artifacts.json").is_file())

    def test_identical_existing_images_resume_without_any_tag_or_push(self):
        self.promote(exists=True)
        self.assertFalse(
            any(
                command[:2] in {("docker", "push"), ("docker", "tag")}
                for command in self.commands
            )
        )

    def test_existing_different_config_is_never_overwritten(self):
        self.remote_config = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ValueError, "different bytes"):
            self.promote(exists=True)
        self.assertFalse(
            any(
                command[:2] in {("docker", "push"), ("docker", "tag")}
                for command in self.commands
            )
        )
        self.assertFalse((self.directory / "release-artifacts.json").exists())

    def test_denied_or_unknown_preflight_stops_actual_promotion_before_tag_or_push(
        self,
    ):
        with (
            patch("release_artifacts.run", side_effect=self.command),
            patch(
                "release_artifacts.dependency_policy_fingerprint",
                return_value="reviewed",
            ),
            patch(
                "release_artifacts.registry_tag_exists",
                side_effect=ValueError("authorization denied"),
            ),
            self.assertRaisesRegex(ValueError, "authorization denied"),
        ):
            artifacts.promote(self.directory, REVISION, self.qualified["deployment"]["target_schema"])
        self.assertFalse(
            any(
                command[:2] in {("docker", "push"), ("docker", "tag")}
                for command in self.commands
            )
        )


if __name__ == "__main__":
    unittest.main()
