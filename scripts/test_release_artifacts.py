"""Fail-closed artifact trust tests; these mocks do not claim a GitHub signature."""
import copy
import datetime as dt
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_artifacts import (
    archive_config,
    dependency_policy_fingerprint,
    registry_config_identity,
    require_current_dependency_policy,
    trust_policy,
    validate_local_config,
    validate_manifest,
    verification_command,
    verify_image_bytes,
    verify_manifest,
)
from release_current import CurrentRelease
from release_traveller_whatsapp import ReleaseError

REVISION = "a" * 40


class ArtifactTrustTests(unittest.TestCase):
    def setUp(self):
        self.policy = trust_policy()
        self.manifest = {"version": 1, "revision": REVISION, "repository": self.policy["repository"],
            "schema": "0109_dashboard_sessions", "images": {}}
        for name in ("backend", "frontend"):
            digest = "sha256:" + ("b" if name == "backend" else "c") * 64
            self.manifest["images"][name] = {"digest": digest, "image_id": "sha256:" + "d" * 64,
                "local_image_id": "sha256:" + "e" * 64,
                "reference": f"{self.policy['registry']}-{name}@{digest}"}

    def test_verifier_pins_repository_workflow_commit_branch_issuer_and_hosted_runner(self):
        args = verification_command("inventory.json", REVISION, self.policy)
        expected = {"--repo": self.policy["repository"], "--source-digest": REVISION,
            "--source-ref": "refs/heads/main", "--cert-oidc-issuer": "https://token.actions.githubusercontent.com",
            "--signer-workflow": f"{self.policy['repository']}/.github/workflows/ci.yml"}
        for flag, value in expected.items():
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertIn("--deny-self-hosted-runners", args)
        self.assertIn("https://spdx.dev/Document", verification_command("oci://image", REVISION, self.policy, sbom=True))

    def test_mutable_tag_wrong_repository_missing_image_wrong_revision_fail(self):
        validate_manifest(self.manifest, REVISION, self.policy)
        for change in ("tag", "repository", "inventory", "revision", "schema"):
            manifest = copy.deepcopy(self.manifest)
            if change == "tag": manifest["images"]["backend"]["reference"] = "ghcr.io/evil/image:latest"
            if change == "repository": manifest["repository"] = "attacker/repo"
            if change == "inventory": del manifest["images"]["frontend"]
            if change == "revision": manifest["revision"] = "f" * 40
            if change == "schema": manifest["schema"] = "head"
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_manifest(manifest, REVISION, self.policy)

    def test_bad_signature_stops_before_docker_pull_or_manifest_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text("invalid even before JSON parsing")
            with patch("release_artifacts.run", side_effect=subprocess.CalledProcessError(1, ["gh"])) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    verify_manifest(path, REVISION, pull=True)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[:3], ("gh", "attestation", "verify"))

    def test_image_config_mismatch_rejected_after_signature_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(json.dumps(self.manifest))
            def fake(*args):
                if args[:3] == ("docker", "image", "inspect"):
                    return json.dumps([{"Id": "sha256:" + "e" * 64, "Os": "linux", "Architecture": "amd64"}])
                if args[:3] == ("docker", "manifest", "inspect"):
                    return json.dumps({"OCIManifest": {"config": {"digest": "sha256:" + "e" * 64}}})
                return "verified by test double"
            with patch("release_artifacts.run", side_effect=fake), self.assertRaisesRegex(ValueError, "config differs"):
                verify_manifest(path, REVISION, pull=True)

    def test_unsigned_current_activation_fails_before_any_deployment_operation(self):
        release = object.__new__(CurrentRelease)
        release.env = {}
        with patch.object(release, "verify_checkout") as checkout:
            with self.assertRaisesRegex(ReleaseError, "signed, qualified"):
                release.activate()
            checkout.assert_not_called()

    def test_promoted_prepare_records_digest_references_without_rebuilding(self):
        release = object.__new__(CurrentRelease)
        release.env = {"RELEASE_ARTIFACT_MANIFEST": "reviewed.json"}
        release.activated_services = ("backend", "worker", "frontend")
        references = {name: "old:tag" for name in release.activated_services}
        with patch.object(release, "artifact_manifest", return_value=self.manifest):
            images = release.prepare_images({}, references)
        self.assertEqual(references["worker"], self.manifest["images"]["backend"]["reference"])
        self.assertEqual(references["frontend"], self.manifest["images"]["frontend"]["reference"])
        self.assertEqual(set(images), set(release.activated_services))
        self.assertEqual(set(images.values()), {"sha256:" + "e" * 64})

    def test_cross_store_ids_preserve_the_same_registry_config(self):
        config_id, local_id = "sha256:" + "d" * 64, "sha256:" + "e" * 64
        reference = self.manifest["images"]["backend"]["reference"]
        image = {"Id": local_id, "Os": "linux", "Architecture": "amd64", "RepoDigests": [reference],
                 "Config": {"Labels": {"org.opencontainers.image.revision": REVISION}}}
        document = [{"Descriptor": {"platform": {"os": "linux", "architecture": "amd64"}},
                     "OCIManifest": {"config": {"digest": config_id}}},
                    {"Descriptor": {"platform": {"os": "unknown", "architecture": "unknown"}},
                     "OCIManifest": {"config": {"digest": "sha256:" + "f" * 64}}}]
        def fake(*args):
            return json.dumps([image]) if args[:3] == ("docker", "image", "inspect") else json.dumps(document)
        with patch("release_artifacts.run", side_effect=fake):
            self.assertEqual(verify_image_bytes(reference, config_id, REVISION, pull=False), local_id)
            image["Id"] = config_id  # Classic store returns config instead of index.
            self.assertEqual(verify_image_bytes(reference, config_id, REVISION, pull=False), config_id)
            image["RepoDigests"] = []
            with self.assertRaisesRegex(ValueError, "not bound"):
                verify_image_bytes(reference, config_id, REVISION, pull=False)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            registry_config_identity([document[0], document[0]], image)

    def test_archive_identity_reads_only_config_and_checks_native_layers(self):
        config = {"config": {"User": "appuser"}, "rootfs": {"diff_ids": ["sha256:a"]},
                  "architecture": "amd64", "os": "linux"}
        raw = json.dumps(config).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.tar"
            with tarfile.open(path, "w") as writer:
                for name, data in (("config.json", raw), ("manifest.json", json.dumps([{
                        "Config": "config.json", "RepoTags": ["synthetic:ci"]}]).encode())):
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    writer.addfile(member, io.BytesIO(data))
            identifier, restored = archive_config(path, "synthetic:ci")
            self.assertEqual(identifier, "sha256:" + hashlib.sha256(raw).hexdigest())
            image = {"Config": restored["config"], "RootFS": {"Layers": ["sha256:a"]},
                     "Architecture": "amd64", "Os": "linux"}
            validate_local_config(image, restored)
            image["RootFS"]["Layers"] = ["sha256:modified"]
            with self.assertRaises(ValueError):
                validate_local_config(image, restored)

    def test_expired_or_changed_signed_policy_cannot_activate(self):
        with (patch("release_artifacts.dependency_policy_fingerprint", side_effect=ValueError("expired")),
              self.assertRaisesRegex(ValueError, "expired")):
            require_current_dependency_policy({"dependency_policy_sha256": "original"})
        with patch("release_artifacts.dependency_policy_fingerprint", return_value="current"):
            with self.assertRaisesRegex(ValueError, "differs"):
                require_current_dependency_policy({"dependency_policy_sha256": "old"})
            require_current_dependency_policy({"dependency_policy_sha256": "current"})

    def test_actual_expiry_date_stops_verified_inventory_before_image_pull(self):
        self.manifest["dependency_policy_sha256"] = dependency_policy_fingerprint(enforce_expiry=False)
        future = dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps(self.manifest))
            with (patch("release_artifacts.dt.datetime") as clock,
                  patch("release_artifacts.run", return_value="signature fixture verified") as command):
                clock.now.return_value = future
                with self.assertRaisesRegex(ValueError, "expired"):
                    verify_manifest(path, REVISION, pull=True, enforce_current_policy=True)
                self.assertEqual(command.call_count, 1)
                self.assertEqual(command.call_args.args[:3], ("gh", "attestation", "verify"))


if __name__ == "__main__":
    unittest.main()
